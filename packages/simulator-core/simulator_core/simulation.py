"""
simulator_core.simulation
~~~~~~~~~~~~~~~~~~~~~~~~~
Simulation runtime: logical clock, event dispatcher, trace recorder, reset.

The Simulation object is the central coordinator.  It owns:
- The logical clock.
- The EventScheduler (priority queue).
- The event trace (inspectable list of all processed events).
- The device protocol objects (Host, Switch) built from the topology.

Device protocol objects call ``simulation.schedule()`` to inject new events.
The dispatcher routes processed events to the correct device handler.

No host I/O, no socket imports.
"""

from __future__ import annotations

import copy
import random
from typing import TYPE_CHECKING, Optional

from simulator_core.events import (
    FrameArrival,
    FrameDropped,
    FrameTransmit,
    SimulationEvent,
    TraceLimitReached,
    BPDUHelloEvent,
    ForwardDelayEvent,
    DROP_LINK_DOWN,
    DROP_INTERFACE_ADMIN_DOWN,
)
from simulator_core.exceptions import SimulationLimitError
from simulator_core.scheduler import EventScheduler
from simulator_core.topology import Topology
from simulator_core.types import InterfaceState, PROPAGATION_DELAY

if TYPE_CHECKING:
    from simulator_core.devices.host import Host
    from simulator_core.devices.switch import Switch
    from simulator_core.devices.router import Router


class Simulation:
    """
    Discrete-event simulation runtime.

    Parameters
    ----------
    topology:
        A validated (or will-be-validated) topology description.
    seed:
        Integer seed for the simulation's PRNG.  Same seed → same trace.
    max_ticks:
        Maximum logical timestamp for any event.  Events beyond this raise
        :class:`~simulator_core.exceptions.SimulationLimitError`.
    max_trace:
        Maximum number of events recorded in the trace.  When reached a
        :class:`~simulator_core.events.TraceLimitReached` sentinel is appended
        and further events are not recorded (the simulation continues).
    max_queue:
        Maximum depth of the event scheduler queue.
    max_nodes, max_links:
        Passed through to topology.validate() for resource-limit checking.
    """

    DEFAULT_MAX_TICKS: int = 3_600
    DEFAULT_MAX_TRACE: int = 50_000
    DEFAULT_MAX_QUEUE: int = 10_000

    def __init__(
        self,
        topology: Topology,
        seed: int = 0,
        max_ticks: int = DEFAULT_MAX_TICKS,
        max_trace: int = DEFAULT_MAX_TRACE,
        max_queue: int = DEFAULT_MAX_QUEUE,
    ) -> None:
        topology.validate()

        # Store a deep copy for reset() so we can always restore initial state.
        self._topology_snapshot: Topology = copy.deepcopy(topology)
        self._topology: Topology = copy.deepcopy(topology)

        self._seed: int = seed
        self._max_ticks: int = max_ticks
        self._max_trace: int = max_trace

        self._rng: random.Random = random.Random(seed)
        self._clock: int = 0
        self._scheduler: EventScheduler = EventScheduler(max_depth=max_queue)
        self._trace: list[SimulationEvent] = []

        # Device protocol objects keyed by device_id.
        self._hosts: dict[str, "Host"] = {}
        self._switches: dict[str, "Switch"] = {}
        self._routers: dict[str, "Router"] = {}
        # Generation counter per switch for BPDUHelloEvent cancellation.
        # Incrementing a switch's generation invalidates all previously
        # scheduled BPDUHelloEvents for that switch (stale-event guard).
        self._hello_generation: dict[str, int] = {}
        # Guard flag: _trigger_stp is a no-op until _init_devices finishes
        # building all Switch objects and running the initial STP election.
        self._stp_initialized: bool = False
        self._init_devices()

    # ------------------------------------------------------------------
    # Public read properties
    # ------------------------------------------------------------------

    @property
    def clock(self) -> int:
        """Current logical tick."""
        return self._clock

    @property
    def trace(self) -> list[SimulationEvent]:
        """A defensive copy of the event trace."""
        return list(self._trace)

    @property
    def topology(self) -> Topology:
        """The working topology (not the reset snapshot)."""
        return self._topology

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def schedule(self, event: SimulationEvent) -> None:
        """
        Schedule an event.

        Raises
        ------
        SimulationLimitError
            If ``event.time > max_ticks`` or the queue depth limit is hit.
        """
        if event.time > self._max_ticks:
            raise SimulationLimitError(
                f"Event at tick {event.time} exceeds max_ticks "
                f"{self._max_ticks}."
            )
        self._scheduler.schedule(event)

    def next_seq(self) -> int:
        """Delegate to the scheduler's sequence counter."""
        return self._scheduler.next_seq()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def step(self) -> Optional[SimulationEvent]:
        """
        Process one event from the queue.

        Returns the processed event, or ``None`` if the queue is empty.
        """
        if self._scheduler.is_empty():
            return None
        event = self._scheduler.pop()
        self._clock = event.time
        self._record(event)
        self._dispatch(event)
        return event

    def run(self) -> None:
        """Process all queued events until the queue is empty."""
        while not self._scheduler.is_empty():
            self.step()

    def reset(self) -> None:
        """
        Restore the simulation to its initial state.

        After reset, replaying the same sequence of host.ping() calls with
        the same arguments will produce the identical event trace.
        """
        self._clock = 0
        self._rng = random.Random(self._seed)
        self._scheduler.clear()
        self._trace.clear()
        self._topology = copy.deepcopy(self._topology_snapshot)
        self._hosts.clear()
        self._switches.clear()
        self._routers.clear()
        # Increment all existing generations so queued BPDUHelloEvents become stale.
        for dev_id in list(self._hello_generation):
            self._hello_generation[dev_id] += 1
        self._stp_initialized = False
        self._init_devices()

    # ------------------------------------------------------------------
    # Device accessors
    # ------------------------------------------------------------------

    def get_host(self, device_id: str) -> "Host":
        """Return the Host protocol object for *device_id*."""
        try:
            return self._hosts[device_id]
        except KeyError:
            raise KeyError(f"No host device with id {device_id!r}.")

    def get_switch(self, device_id: str) -> "Switch":
        """Return the Switch protocol object for *device_id*."""
        try:
            return self._switches[device_id]
        except KeyError:
            raise KeyError(f"No switch device with id {device_id!r}.")

    def get_router(self, device_id: str) -> "Router":
        """Return the Router protocol object for *device_id*."""
        try:
            return self._routers[device_id]
        except KeyError:
            raise KeyError(f"No router device with id {device_id!r}.")

    def run_stp(self) -> None:
        """
        Run STP/PVST+ root election and port-role calculation across all
        switches in the topology.

        Call this after the topology is fully connected (all links added)
        or after any change that affects the spanning tree:
         - Bridge priority change
         - Port cost change
         - Link added or removed
         - Interface shut down or brought up
         - VLAN membership change

        The election uses the topology's actual Link objects to discover
        peer switches — no direct cross-object references or hardcoded roots.

        Each STPManager.recalculate() call receives:
         - the topology (for link discovery via topology.neighbours())
         - the full dict of peer STPManagers (for Bridge ID comparison)

        Convergence: iterates until two consecutive snapshots are equal or
        until MAX_ITER (32) iterations, whichever comes first.  32 iterations
        is more than sufficient for realistic educational topologies.
        """
        if not self._switches:
            return
        all_stps = {dev_id: sw.stp for dev_id, sw in self._switches.items()}
        MAX_ITER = 32
        for _iteration in range(MAX_ITER):
            before = self._stp_snapshot()
            # Sorted iteration order for determinism
            for dev_id in sorted(self._switches):
                self._switches[dev_id].stp.recalculate(self._topology, all_stps)
            after = self._stp_snapshot()
            if after == before:
                break  # stable state reached

    def _stp_snapshot(self) -> dict:
        """Snapshot relevant STP state for convergence detection."""
        snap: dict = {}
        for dev_id, sw in sorted(self._switches.items()):
            snap[dev_id] = {}
            for vlan_id, inst in sw.stp._instances.items():
                ports = {
                    pname: (ps.role, ps.state)
                    for pname, ps in inst.port_states.items()
                }
                snap[dev_id][vlan_id] = (
                    inst.root_bridge_id,
                    inst.root_path_cost,
                    inst.root_port_name,
                    ports,
                )
        return snap

    def _trigger_stp(self) -> None:
        """
        Trigger STP recalculation if the simulation has finished initialising.

        This guard prevents spurious recalculations while _init_devices is
        still building the switch map (before all switches are created).
        """
        if self._stp_initialized:
            self.run_stp()

    def add_link(self, link: "object") -> None:
        """
        Add a link to the working topology and trigger STP recalculation.

        Callers should use this method (rather than topology.add_link directly)
        after Simulation init so that STP converges automatically.
        """
        from simulator_core.topology import Link as _Link
        assert isinstance(link, _Link)
        self._topology.add_link(link)
        self._trigger_stp()

    def remove_link(self, link_id: str) -> None:
        """
        Remove a link from the working topology by ID and trigger STP recalculation.

        Callers should use this method (rather than topology.remove_link directly)
        after Simulation init so that STP converges automatically.
        """
        self._topology.remove_link(link_id)
        self._trigger_stp()

    def start_hello_timers(self, start_tick: int = 0) -> None:
        """
        Start (or restart) the periodic BPDU hello chain for all switches.

        Call this after Simulation init (or after reset + init) to begin
        periodic BPDU transmission.  Increments each switch's hello
        generation to invalidate any previously-scheduled chains, then
        schedules the first BPDUHelloEvent at start_tick + hello_time.

        This method is intentionally NOT called automatically from
        _init_devices() to avoid flooding the event queue in unit tests
        that use sim.run() without expecting background BPDU traffic.
        """
        for dev_id in sorted(self._switches):
            # Bump generation to cancel any old chain
            gen = self._hello_generation.get(dev_id, 0) + 1
            self._hello_generation[dev_id] = gen
            self._schedule_next_hello(dev_id, start_tick=start_tick)

    def send_bpdus(self, tick: int = 0) -> None:
        """
        Send BPDUs from all eligible switch ports through the frame pipeline.

        For each switch, for each STP instance (VLAN), for each port that is
        FORWARDING or the root port or a designated port, build a BPDU and
        schedule a FrameTransmit event.  Only ports that are physically
        connected (topology.neighbours returns non-None) and administratively
        UP transmit.

        BPDUs use dst_mac=01:80:c2:00:00:00 (STP multicast) and are carried
        as EthernetFrame.bpdu_payload.  They bypass normal MAC learning and
        STP forwarding checks on receipt.

        Phase 3: calling send_bpdus() does NOT cancel the periodic hello
        chain.  It is a one-shot explicit call used for tests and
        initialisation.  The periodic chain runs independently via
        BPDUHelloEvent.
        """
        import uuid as _uuid
        from simulator_core.frames import EthernetFrame, STP_MULTICAST_MAC
        from simulator_core.stp import BPDU, PortRole
        from simulator_core.addresses import MACAddress
        from simulator_core.types import InterfaceState

        for dev_id in sorted(self._switches):
            sw = self._switches[dev_id]
            device = self._topology.devices.get(dev_id)
            if device is None:
                continue
            for inst in sw.stp.all_instances():
                if inst.bridge_id is None:
                    continue
                for port_name, port_state in inst.port_states.items():
                    # Only send from ports with an eligible role
                    if port_state.role not in (
                        PortRole.DESIGNATED, PortRole.ROOT, PortRole.EDGE
                    ):
                        continue
                    # Phase 6: BPDUFilter suppresses BPDU transmission
                    if port_state.bpdufilter:
                        continue
                    # Must be physically connected
                    peer = self._topology.neighbours(dev_id, port_name)
                    if peer is None:
                        continue
                    # Egress interface must be UP
                    iface = device.interfaces.get(port_name)
                    if iface is None or iface.admin_state == InterfaceState.DOWN:
                        continue
                    # Phase 4: set message_age based on best_bpdu
                    if port_state.best_bpdu is not None:
                        message_age = port_state.best_bpdu.message_age + 1
                    else:
                        message_age = 0  # we are root for this VLAN
                    # Build BPDU
                    bpdu = BPDU(
                        version=2 if sw.stp.mode.value == "rapid-pvst" else 0,
                        root_bridge_id=inst.root_bridge_id,
                        root_path_cost=inst.root_path_cost,
                        bridge_id=inst.bridge_id,
                        port_id=port_state.port_id,
                        message_age=message_age,
                        max_age=inst.timers.max_age,
                        hello_time=inst.timers.hello_time,
                        forward_delay=inst.timers.forward_delay,
                    )
                    # Build EthernetFrame wrapping the BPDU
                    src_mac = iface.mac
                    dst_mac = MACAddress(STP_MULTICAST_MAC)
                    frame = EthernetFrame(
                        src_mac=src_mac,
                        dst_mac=dst_mac,
                        ethertype=EthernetFrame.ETHERTYPE_BPDU,
                        frame_id=str(_uuid.uuid4()),
                        bpdu_payload=bpdu,
                    )
                    # Increment tx counter
                    port_state.bpdu_tx += 1
                    # Schedule FrameTransmit
                    try:
                        self.schedule(FrameTransmit(
                            time=tick,
                            seq=self.next_seq(),
                            device_id=dev_id,
                            interface_name=port_name,
                            frame=frame,
                        ))
                    except Exception:
                        pass  # skip if tick exceeds max_ticks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_devices(self) -> None:
        """Instantiate Host, Switch and Router protocol objects from the topology."""
        # Deferred imports to avoid circular references at module load time.
        from simulator_core.devices.host import Host
        from simulator_core.devices.switch import Switch
        from simulator_core.devices.router import Router
        from simulator_core.types import DeviceModel

        # Guard against _trigger_stp calls while switches are being created.
        self._stp_initialized = False

        for device in self._topology.devices.values():
            if device.model == DeviceModel.HOST:
                self._hosts[device.id] = Host(device=device, simulation=self)
            elif device.model == DeviceModel.SWITCH:
                self._switches[device.id] = Switch(device=device, simulation=self)
            elif device.model == DeviceModel.ROUTER:
                self._routers[device.id] = Router(device=device, simulation=self)
                # Build initial connected routes from interface IPs
                self._routers[device.id].update_connected_routes()

        # Run initial STP election now that all switches are instantiated
        # and the topology links are known.
        self.run_stp()
        # Allow _trigger_stp to run from this point on.
        self._stp_initialized = True
        # NOTE: Periodic BPDU hello chains are NOT started automatically.
        # Call start_hello_timers() explicitly after Simulation init to enable
        # periodic BPDU transmission.  This avoids flooding the event queue
        # during unit tests that use sim.run() without expecting BPDU traffic.

    def _record(self, event: SimulationEvent) -> None:
        """Append the event to the trace, enforcing the trace size cap."""
        if len(self._trace) >= self._max_trace:
            # Append a sentinel at most once per cap crossing.
            if not (self._trace and isinstance(self._trace[-1], TraceLimitReached)):
                sentinel = TraceLimitReached(
                    time=self._clock,
                    seq=self._scheduler.next_seq(),
                    limit=self._max_trace,
                )
                self._trace.append(sentinel)
            return
        self._trace.append(event)

    def _dispatch(self, event: SimulationEvent) -> None:
        """Route a processed event to the correct device handler."""
        if isinstance(event, FrameTransmit):
            self._deliver_frame(event)
        elif isinstance(event, FrameArrival):
            self._handle_frame_arrival(event)
        elif isinstance(event, BPDUHelloEvent):
            self._handle_bpdu_hello(event)
        elif isinstance(event, ForwardDelayEvent):
            self._handle_forward_delay(event)
        # Other event types (ARP*, ICMP*, MACTable*, drops) are purely
        # observational records — they do not trigger further dispatch.

    def _deliver_frame(self, event: FrameTransmit) -> None:
        """
        Convert a FrameTransmit into a FrameArrival on the peer interface.

        Checks the link state and egress interface state before delivery.
        Schedules a FrameDropped if either is DOWN.
        """
        device_id = event.device_id
        iface_name = event.interface_name
        frame = event.frame

        # --- Check egress interface admin state ---
        device = self._topology.devices.get(device_id)
        if device is None:
            return  # should never happen after validation
        iface = device.interfaces.get(iface_name)
        if iface is None:
            return
        if iface.admin_state == InterfaceState.DOWN:
            self._drop(
                time=event.time + PROPAGATION_DELAY,
                device_id=device_id,
                iface_name=iface_name,
                frame=frame,
                reason=DROP_INTERFACE_ADMIN_DOWN,
            )
            return

        # --- Look up the link ---
        link = self._topology.get_link(device_id, iface_name)
        if link is None or link.admin_state == InterfaceState.DOWN:
            self._drop(
                time=event.time + PROPAGATION_DELAY,
                device_id=device_id,
                iface_name=iface_name,
                frame=frame,
                reason=DROP_LINK_DOWN,
            )
            return

        # --- Find peer ---
        peer = self._topology.neighbours(device_id, iface_name)
        if peer is None:
            # Unconnected interface — drop silently (no peer to receive).
            return

        peer_device_id, peer_iface_name = peer

        # --- Check peer interface admin state ---
        peer_device = self._topology.devices.get(peer_device_id)
        if peer_device is None:
            return
        peer_iface = peer_device.interfaces.get(peer_iface_name)
        if peer_iface is None:
            return
        if peer_iface.admin_state == InterfaceState.DOWN:
            self._drop(
                time=event.time + PROPAGATION_DELAY,
                device_id=peer_device_id,
                iface_name=peer_iface_name,
                frame=frame,
                reason=DROP_INTERFACE_ADMIN_DOWN,
            )
            return

        # --- Schedule FrameArrival ---
        arrive_time = event.time + PROPAGATION_DELAY
        seq = self._scheduler.next_seq()
        arrival = FrameArrival(
            time=arrive_time,
            seq=seq,
            device_id=peer_device_id,
            interface_name=peer_iface_name,
            frame=frame,
        )
        self.schedule(arrival)

        # Update counters.
        if iface is not None:
            iface.tx_frames += 1
        if peer_iface is not None:
            peer_iface.rx_frames += 1

    def _handle_frame_arrival(self, event: FrameArrival) -> None:
        """Route a FrameArrival to the owning device's protocol handler."""
        from simulator_core.types import DeviceModel

        device = self._topology.devices.get(event.device_id)
        if device is None:
            return

        if device.model == DeviceModel.HOST:
            host = self._hosts.get(event.device_id)
            if host is not None:
                host.handle_frame_arrival(event)
        elif device.model == DeviceModel.SWITCH:
            switch = self._switches.get(event.device_id)
            if switch is not None:
                switch.handle_frame_arrival(event)
        elif device.model == DeviceModel.ROUTER:
            router = self._routers.get(event.device_id)
            if router is not None:
                router.handle_frame_arrival(event)

    def _drop(
        self,
        time: int,
        device_id: str,
        iface_name: Optional[str],
        frame: object,  # EthernetFrame
        reason: str,
    ) -> None:
        """Schedule a FrameDropped event and record it immediately."""
        from simulator_core.frames import EthernetFrame

        assert isinstance(frame, EthernetFrame)
        seq = self._scheduler.next_seq()
        drop = FrameDropped(
            time=time,
            seq=seq,
            device_id=device_id,
            interface_name=iface_name,
            frame=frame,
            reason=reason,
        )
        # Record drop events directly rather than scheduling them through the
        # queue — they are consequences of the current event, not future work.
        self._record(drop)

    # ------------------------------------------------------------------
    # BPDU hello timer helpers (Phase 3)
    # ------------------------------------------------------------------

    def _schedule_next_hello(self, device_id: str, start_tick: int) -> None:
        """
        Schedule the next BPDUHelloEvent for a switch.

        Reads the hello_time from the first STP instance on the switch
        (hello_time is uniform across instances).  Uses the switch's
        current generation so any previously-queued events for older
        generations will be silently ignored when processed.

        The chain stops when the next fire tick would exceed
        max_ticks - PROPAGATION_DELAY (so that any BPDUs generated by
        this hello can still be delivered within the simulation window).
        """
        sw = self._switches.get(device_id)
        if sw is None:
            return
        # Determine hello_time (in ticks = seconds for this model)
        hello_ticks = 2  # default
        for inst in sw.stp.all_instances():
            hello_ticks = inst.timers.hello_time
            break
        fire_at = start_tick + hello_ticks
        # Stop chain before BPDUs generated here would exceed max_ticks
        if fire_at + PROPAGATION_DELAY > self._max_ticks:
            return
        # Assign/read generation for this switch
        gen = self._hello_generation.get(device_id, 0)
        self._hello_generation[device_id] = gen
        try:
            self.schedule(BPDUHelloEvent(
                time=fire_at,
                seq=self.next_seq(),
                device_id=device_id,
                generation=gen,
            ))
        except Exception:
            pass  # tick exceeds max_ticks — stop the chain silently

    def _handle_bpdu_hello(self, event: BPDUHelloEvent) -> None:
        """
        Handle a BPDUHelloEvent: validate generation, send BPDUs, reschedule.

        If the event's generation is stale (< current generation for this
        switch), it is ignored — the old chain has been superseded by a
        newer one started after a reset or topology change.
        """
        dev_id = event.device_id
        current_gen = self._hello_generation.get(dev_id, 0)
        if event.generation != current_gen:
            # Stale event from an old hello chain — discard it.
            return
        # Send BPDUs for this switch at the current tick.
        self._send_bpdus_for_switch(dev_id, tick=self._clock)
        # Schedule the next hello
        self._schedule_next_hello(dev_id, start_tick=self._clock)

    def _send_bpdus_for_switch(self, device_id: str, tick: int) -> None:
        """
        Send BPDUs from one switch at the given tick.

        This is the per-switch variant called by the hello timer.  Identical
        logic to send_bpdus() but scoped to a single switch.  Also performs
        per-port max-age expiry check (Phase 4).
        """
        import uuid as _uuid
        from simulator_core.frames import EthernetFrame, STP_MULTICAST_MAC
        from simulator_core.stp import BPDU, PortRole
        from simulator_core.addresses import MACAddress
        from simulator_core.types import InterfaceState

        sw = self._switches.get(device_id)
        if sw is None:
            return
        device = self._topology.devices.get(device_id)
        if device is None:
            return

        for inst in sw.stp.all_instances():
            if inst.bridge_id is None:
                continue

            # Phase 4: check max-age expiry on all ports before sending
            self._check_max_age_expiry(sw, inst, tick)

            for port_name, port_state in inst.port_states.items():
                if port_state.role not in (
                    PortRole.DESIGNATED, PortRole.ROOT, PortRole.EDGE
                ):
                    continue
                # Phase 6: BPDUFilter suppresses BPDU transmission
                if port_state.bpdufilter:
                    continue
                peer = self._topology.neighbours(device_id, port_name)
                if peer is None:
                    continue
                iface = device.interfaces.get(port_name)
                if iface is None or iface.admin_state == InterfaceState.DOWN:
                    continue

                # Phase 4: set message_age based on best_bpdu
                if port_state.best_bpdu is not None:
                    message_age = port_state.best_bpdu.message_age + 1
                else:
                    message_age = 0  # we are root for this VLAN

                bpdu = BPDU(
                    version=2 if sw.stp.mode.value == "rapid-pvst" else 0,
                    root_bridge_id=inst.root_bridge_id,
                    root_path_cost=inst.root_path_cost,
                    bridge_id=inst.bridge_id,
                    port_id=port_state.port_id,
                    message_age=message_age,
                    max_age=inst.timers.max_age,
                    hello_time=inst.timers.hello_time,
                    forward_delay=inst.timers.forward_delay,
                )
                src_mac = iface.mac
                dst_mac = MACAddress(STP_MULTICAST_MAC)
                frame = EthernetFrame(
                    src_mac=src_mac,
                    dst_mac=dst_mac,
                    ethertype=EthernetFrame.ETHERTYPE_BPDU,
                    frame_id=str(_uuid.uuid4()),
                    bpdu_payload=bpdu,
                )
                port_state.bpdu_tx += 1
                try:
                    self.schedule(FrameTransmit(
                        time=tick,
                        seq=self.next_seq(),
                        device_id=device_id,
                        interface_name=port_name,
                        frame=frame,
                    ))
                except Exception:
                    pass

    def _check_max_age_expiry(self, sw: "Switch", inst: "object", tick: int) -> None:
        """
        Phase 4: expire best_bpdu on ports that have not received a BPDU
        refresh within max_age ticks.  Triggers local recalculation when
        a port's best_bpdu expires.
        """
        from simulator_core.stp import STPInstance
        assert isinstance(inst, STPInstance)
        max_age_ticks = inst.timers.max_age
        changed = False
        for port_name, ps in inst.port_states.items():
            if ps.best_bpdu is None:
                continue
            if ps.last_bpdu_tick < 0:
                # Never received a BPDU — do not expire
                continue
            age = tick - ps.last_bpdu_tick
            if age > max_age_ticks:
                # BPDU too old — clear it and trigger recalculation
                ps.best_bpdu = None
                changed = True
        if changed:
            new_learning = sw.stp.recalculate_from_bpdus(inst)
            # Phase 5: schedule ForwardDelayEvents for ports entering LEARNING
            for lport in new_learning:
                self.schedule_forward_delay(
                    device_id=sw.device_id,
                    interface_name=lport,
                    vlan_id=inst.vlan_id,
                    at_tick=self._clock + inst.timers.forward_delay,
                )

    # ------------------------------------------------------------------
    # Forward-delay timer helper (Phase 5)
    # ------------------------------------------------------------------

    def schedule_forward_delay(
        self,
        device_id: str,
        interface_name: str,
        vlan_id: int,
        at_tick: int,
    ) -> None:
        """
        Schedule a ForwardDelayEvent for a port transitioning LEARNING→FORWARDING.

        Called by recalculate_from_bpdus or _recalculate_instance_with_peers
        when a port enters LEARNING state.
        """
        gen = self._hello_generation.get(device_id, 0)
        try:
            self.schedule(ForwardDelayEvent(
                time=at_tick,
                seq=self.next_seq(),
                device_id=device_id,
                interface_name=interface_name,
                vlan_id=vlan_id,
                generation=gen,
            ))
        except Exception:
            pass  # tick exceeds max_ticks

    def _handle_forward_delay(self, event: ForwardDelayEvent) -> None:
        """
        Phase 5: transition port from LEARNING → FORWARDING.

        Only transitions the port if it is still in LEARNING state at fire
        time (a topology change may have already moved it).
        """
        from simulator_core.stp import PortState

        sw = self._switches.get(event.device_id)
        if sw is None:
            return
        inst = sw.stp.get_instance(event.vlan_id)
        if inst is None:
            return
        ps = inst.port_states.get(event.interface_name)
        if ps is None:
            return
        # Only advance if still in LEARNING
        if ps.state == PortState.LEARNING:
            ps.state = PortState.FORWARDING
