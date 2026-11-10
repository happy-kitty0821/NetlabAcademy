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

        for device in self._topology.devices.values():
            if device.model == DeviceModel.HOST:
                self._hosts[device.id] = Host(device=device, simulation=self)
            elif device.model == DeviceModel.SWITCH:
                self._switches[device.id] = Switch(device=device, simulation=self)
            elif device.model == DeviceModel.ROUTER:
                self._routers[device.id] = Router(device=device, simulation=self)
                # Build initial connected routes from interface IPs
                self._routers[device.id].update_connected_routes()

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
