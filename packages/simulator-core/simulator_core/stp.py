"""
simulator_core.stp
~~~~~~~~~~~~~~~~~~
Spanning Tree Protocol implementation.

Supports:
  - STP  (802.1D)  — Classic spanning tree
  - RSTP (802.1w)  — Rapid spanning tree
  - PVST+          — Per-VLAN spanning tree (Cisco proprietary)
  - Rapid-PVST+    — Rapid per-VLAN spanning tree

IEEE 802.1D port states:
  Blocking → Listening → Learning → Forwarding → Disabled

IEEE 802.1w / RSTP port states (simplified to 3):
  Discarding → Learning → Forwarding

Port roles (RSTP):
  Root Port      — best path to root bridge
  Designated Port— best port on a LAN segment
  Alternate Port  — backup path to root (Blocking in STP)
  Backup Port     — backup on the same LAN segment

Bridge ID format:
  priority (2 bytes, default 32768) + system-id-extension (12-bit VLAN) +
  MAC address (6 bytes)

No host I/O, no sockets, no subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# STP mode
# ---------------------------------------------------------------------------

class STPMode(Enum):
    """Global STP mode on the switch."""
    PVST       = "pvst"
    RAPID_PVST = "rapid-pvst"
    MST        = "mst"


# ---------------------------------------------------------------------------
# Port state
# ---------------------------------------------------------------------------

class PortState(Enum):
    """IEEE 802.1D port state machine."""
    DISABLED    = "disabled"
    BLOCKING    = "blocking"
    LISTENING   = "listening"
    LEARNING    = "learning"
    FORWARDING  = "forwarding"

    # RSTP collapsed state
    DISCARDING  = "discarding"


class PortRole(Enum):
    """RSTP port role."""
    ROOT        = "root"
    DESIGNATED  = "designated"
    ALTERNATE   = "alternate"
    BACKUP      = "backup"
    DISABLED    = "disabled"
    EDGE        = "edge"       # PortFast edge port


# ---------------------------------------------------------------------------
# STP timers (in logical ticks)
# ---------------------------------------------------------------------------

@dataclass
class STPTimers:
    hello_time:    int = 2     # seconds between BPDUs (each second = X ticks)
    max_age:       int = 20    # max BPDU age
    forward_delay: int = 15    # listening + learning duration each


# ---------------------------------------------------------------------------
# Bridge ID
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class BridgeID:
    """
    STP Bridge ID: priority + system-id-extension + MAC.
    Lower bridge ID wins root bridge election.
    """
    priority:     int    # 0-61440, multiples of 4096
    sys_id_ext:   int    # VLAN ID (0-4095) for PVST+
    mac:          str    # Normalised lowercase colon-hex MAC

    @property
    def bridge_priority(self) -> int:
        """Full bridge priority (priority + sys_id_ext)."""
        return self.priority + self.sys_id_ext

    def __str__(self) -> str:
        return f"{self.bridge_priority} ({self.mac})"


# ---------------------------------------------------------------------------
# Port ID
# ---------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class PortID:
    """Port ID: priority (1 byte) + port number (1 byte)."""
    priority: int   # 0-240, multiples of 16
    number:   int   # port number

    @property
    def value(self) -> int:
        return (self.priority << 8) | self.number

    def __str__(self) -> str:
        return f"{self.priority}.{self.number}"


# ---------------------------------------------------------------------------
# BPDU
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BPDU:
    """
    STP/RSTP Configuration BPDU.
    """
    # Protocol version: 0 = STP, 2 = RSTP
    version:        int

    # Flags
    topology_change:        bool = False
    topology_change_ack:    bool = False
    agreement:              bool = False   # RSTP
    forwarding:             bool = False   # RSTP
    learning:               bool = False   # RSTP
    port_role:              int  = 0       # RSTP: 0=unknown,1=alt,2=root,3=desig

    # Bridge information
    root_bridge_id:    Optional[BridgeID] = None
    root_path_cost:    int = 0
    bridge_id:         Optional[BridgeID] = None
    port_id:           Optional[PortID]   = None

    # Timers
    message_age:       int = 0
    max_age:           int = 20
    hello_time:        int = 2
    forward_delay:     int = 15


# ---------------------------------------------------------------------------
# STP port state per VLAN
# ---------------------------------------------------------------------------

@dataclass
class STPPortState:
    """
    Per-port, per-VLAN STP state.
    One of these exists for every (port, vlan) combination in STP.
    """
    interface_name: str
    vlan_id:        int

    state:     PortState = PortState.BLOCKING
    role:      PortRole  = PortRole.DESIGNATED

    # Port cost (auto-computed from speed, or manually set)
    path_cost: int = 19          # Default for 100 Mbps (IOS default)
    port_id:   Optional[PortID] = None

    # Port-fast
    portfast:   bool = False
    bpduguard:  bool = False
    bpdufilter: bool = False
    guard:      str  = "none"    # "none" | "root" | "loop"

    # Best BPDU received on this port (used for role calculation)
    best_bpdu: Optional[BPDU] = None

    # BPDU counters
    bpdu_tx: int = 0
    bpdu_rx: int = 0

    @property
    def is_forwarding(self) -> bool:
        return self.state == PortState.FORWARDING

    @property
    def is_learning_or_forwarding(self) -> bool:
        return self.state in (PortState.LEARNING, PortState.FORWARDING)

    @property
    def is_blocking(self) -> bool:
        return self.state in (PortState.BLOCKING, PortState.DISCARDING,
                              PortState.DISABLED)


# ---------------------------------------------------------------------------
# STP instance (per VLAN for PVST+, global for MST)
# ---------------------------------------------------------------------------

@dataclass
class STPInstance:
    """
    One spanning tree instance.

    For PVST+: one instance per VLAN.
    For 802.1D (classic): one instance for all VLANs.
    """
    vlan_id:     int        # 0 = all VLANs (classic STP)
    mode:        STPMode    = STPMode.RAPID_PVST

    # This switch's bridge ID
    bridge_id:   Optional[BridgeID] = None

    # Currently believed root bridge
    root_bridge_id:    Optional[BridgeID] = None
    root_path_cost:    int = 0
    root_port_name:    Optional[str] = None   # name of root port interface

    # Timers
    timers: STPTimers = field(default_factory=STPTimers)

    # Per-port state: interface_name → STPPortState
    port_states: dict[str, STPPortState] = field(default_factory=dict)

    # Whether this switch IS the root bridge
    @property
    def is_root(self) -> bool:
        return (self.root_bridge_id is not None and
                self.bridge_id is not None and
                self.root_bridge_id == self.bridge_id)

    def get_port(self, name: str) -> Optional[STPPortState]:
        return self.port_states.get(name)

    def all_ports(self) -> list[STPPortState]:
        return list(self.port_states.values())


# ---------------------------------------------------------------------------
# STP manager (lives on the Switch device object)
# ---------------------------------------------------------------------------

class STPManager:
    """
    STP/RSTP/PVST+ manager for a switch.

    One STPManager per switch.  Internally maintains one STPInstance per
    active VLAN (PVST+) or one global instance (classic STP/RSTP).

    The simulation calls recalculate() after any topology change (port up/down,
    VLAN change, priority change).  The manager recomputes all port roles and
    states using a simplified election algorithm.

    Simplified election (educational):
    - Each switch starts as root bridge for each VLAN.
    - Root bridge election: lowest Bridge ID wins.
    - Since we don't have real BPDU exchange between devices in the frame
      model yet, the election is computed locally per simulation run.
    - When two switches are connected by trunk links, the topology is known
      through the simulator's topology object; we compute STP directly.
    """

    def __init__(self, device_id: str, mac: str) -> None:
        self._device_id = device_id
        self._mac = mac
        self._mode = STPMode.RAPID_PVST
        self._global_priority = 32768    # default bridge priority

        # Per-VLAN STP instances: vlan_id → STPInstance
        self._instances: dict[int, STPInstance] = {}

        # Feature flags
        self._stp_enabled: bool = True
        self._portfast_default: bool = False    # portfast default on access ports

        # Initialize default instance for VLAN 1
        self._get_or_create_instance(1)

    # ------------------------------------------------------------------
    # Configuration API
    # ------------------------------------------------------------------

    @property
    def mode(self) -> STPMode:
        return self._mode

    @mode.setter
    def mode(self, value: STPMode) -> None:
        self._mode = value

    @property
    def enabled(self) -> bool:
        return self._stp_enabled

    def disable_stp(self, vlan_id: Optional[int] = None) -> None:
        """Globally or per-VLAN disable STP."""
        if vlan_id is None:
            self._stp_enabled = False
        else:
            inst = self._instances.get(vlan_id)
            if inst:
                for port in inst.port_states.values():
                    port.state = PortState.FORWARDING
                    port.role  = PortRole.DESIGNATED

    def set_bridge_priority(self, vlan_id: int, priority: int) -> None:
        """Set bridge priority for a VLAN. Must be a multiple of 4096."""
        if priority % 4096 != 0:
            raise ValueError(
                f"Bridge priority must be a multiple of 4096 (got {priority}). "
                f"Valid values: 0, 4096, 8192, ..., 61440."
            )
        if not (0 <= priority <= 61440):
            raise ValueError(f"Bridge priority must be 0-61440, got {priority}.")
        inst = self._get_or_create_instance(vlan_id)
        inst.bridge_id = BridgeID(
            priority=priority,
            sys_id_ext=vlan_id,
            mac=self._mac,
        )
        self._recalculate_instance(inst)

    def set_root_primary(self, vlan_id: int) -> None:
        """Set this switch as the primary root (priority 24576)."""
        self.set_bridge_priority(vlan_id, 24576)

    def set_root_secondary(self, vlan_id: int) -> None:
        """Set this switch as the secondary root (priority 28672)."""
        self.set_bridge_priority(vlan_id, 28672)

    def set_port_priority(self, iface_name: str, vlan_id: int, priority: int) -> None:
        """Set port priority for a specific interface and VLAN."""
        if priority % 16 != 0:
            raise ValueError(f"Port priority must be a multiple of 16, got {priority}.")
        inst = self._get_or_create_instance(vlan_id)
        port = self._get_or_create_port(inst, iface_name)
        port.port_id = PortID(priority=priority, number=port.port_id.number if port.port_id else 0)

    def set_port_cost(self, iface_name: str, vlan_id: int, cost: int) -> None:
        """Manually set port path cost."""
        if not (1 <= cost <= 200000000):
            raise ValueError(f"Path cost must be 1-200000000, got {cost}.")
        inst = self._get_or_create_instance(vlan_id)
        port = self._get_or_create_port(inst, iface_name)
        port.path_cost = cost

    def set_portfast(self, iface_name: str, enabled: bool) -> None:
        """Enable or disable PortFast on an interface (all VLANs)."""
        for inst in self._instances.values():
            port = self._get_or_create_port(inst, iface_name)
            port.portfast = enabled
            if enabled:
                port.state = PortState.FORWARDING
                port.role  = PortRole.EDGE

    def set_bpduguard(self, iface_name: str, enabled: bool) -> None:
        for inst in self._instances.values():
            port = self._get_or_create_port(inst, iface_name)
            port.bpduguard = enabled

    def set_bpdufilter(self, iface_name: str, enabled: bool) -> None:
        for inst in self._instances.values():
            port = self._get_or_create_port(inst, iface_name)
            port.bpdufilter = enabled

    def set_guard(self, iface_name: str, guard_type: str) -> None:
        """Set guard type: 'root', 'loop', or 'none'."""
        for inst in self._instances.values():
            port = self._get_or_create_port(inst, iface_name)
            port.guard = guard_type

    # ------------------------------------------------------------------
    # Port state query
    # ------------------------------------------------------------------

    def get_port_state(self, iface_name: str, vlan_id: int = 1) -> PortState:
        """Return the STP state for a port in a given VLAN."""
        if not self._stp_enabled:
            return PortState.FORWARDING
        inst = self._instances.get(vlan_id)
        if inst is None:
            return PortState.FORWARDING
        port = inst.port_states.get(iface_name)
        if port is None:
            return PortState.FORWARDING
        return port.state

    def is_port_forwarding(self, iface_name: str, vlan_id: int = 1) -> bool:
        return self.get_port_state(iface_name, vlan_id) == PortState.FORWARDING

    def is_port_learning_or_forwarding(self, iface_name: str, vlan_id: int = 1) -> bool:
        """
        True if the port is in LEARNING or FORWARDING state.

        MAC learning is allowed in both states per IEEE 802.1D.  In the
        current educational model ports transition directly to FORWARDING
        (timer-driven LEARNING state is not simulated), so this is equivalent
        to is_port_forwarding for now.  The method is provided as a public API
        for callers that need to be explicit about learning behaviour.

        # In RSTP/Rapid-PVST the data plane gate is FORWARDING; LEARNING state
        # (timer-driven transitions) is deferred — ports go directly to
        # FORWARDING in the current educational model.
        """
        return self.get_port_state(iface_name, vlan_id) in (
            PortState.LEARNING, PortState.FORWARDING
        )

    def get_instance(self, vlan_id: int) -> Optional[STPInstance]:
        return self._instances.get(vlan_id)

    def all_instances(self) -> list[STPInstance]:
        return list(self._instances.values())

    # ------------------------------------------------------------------
    # Recalculation
    # ------------------------------------------------------------------

    def recalculate(self, topology, all_switches: dict[str, "STPManager"]) -> None:
        """
        Recompute STP for all VLAN instances.

        Called by the simulation after topology changes (port up/down,
        VLAN membership change, priority change).

        Algorithm (simplified PVST+ root election):
        1. For each VLAN, find all switches that participate.
        2. Elect root bridge: switch with lowest Bridge ID.
        3. Assign Root Port on each non-root switch.
        4. Assign Designated / Alternate roles to remaining ports.
        5. Set port states accordingly.
        """
        for vlan_id in list(self._instances.keys()):
            inst = self._instances[vlan_id]
            self._recalculate_instance_with_peers(inst, topology, all_switches)

    def _recalculate_instance(self, inst: STPInstance) -> None:
        """Local recalculation (no peer info) — treats self as root."""
        bid = inst.bridge_id
        if bid is None:
            bid = BridgeID(
                priority=self._global_priority,
                sys_id_ext=inst.vlan_id,
                mac=self._mac,
            )
            inst.bridge_id = bid
        # Without peer info, assume we are root
        inst.root_bridge_id = bid
        inst.root_path_cost = 0
        inst.root_port_name = None
        # Set all ports to Designated / Forwarding
        for port in inst.port_states.values():
            if not port.portfast:
                port.role  = PortRole.DESIGNATED
                port.state = PortState.FORWARDING

    def _recalculate_instance_with_peers(
        self,
        inst: STPInstance,
        topology,
        all_switches: dict[str, "STPManager"],
    ) -> None:
        """
        Full PVST+ root election using the known topology.

        For each VLAN instance:
        1. Build the set of participating switches (those with this VLAN).
        2. Elect root bridge (lowest bridge ID).
        3. For each non-root switch, find the port with lowest root path cost.
        4. Assign roles and states.
        """
        # Ensure bridge ID is set
        if inst.bridge_id is None:
            inst.bridge_id = BridgeID(
                priority=self._global_priority,
                sys_id_ext=inst.vlan_id,
                mac=self._mac,
            )

        vlan_id = inst.vlan_id

        # Collect all participating bridge IDs (this switch + connected switches)
        all_bids: list[BridgeID] = [inst.bridge_id]
        for peer_id, peer_stp in all_switches.items():
            if peer_id == self._device_id:
                continue
            peer_inst = peer_stp.get_instance(vlan_id)
            if peer_inst and peer_inst.bridge_id:
                all_bids.append(peer_inst.bridge_id)

        # Elect root: lowest bridge ID wins
        root_bid = min(all_bids)
        inst.root_bridge_id = root_bid
        is_root = (root_bid == inst.bridge_id)

        if is_root:
            inst.root_path_cost = 0
            inst.root_port_name = None
            # All ports are designated
            for port in inst.port_states.values():
                if port.portfast:
                    port.role  = PortRole.EDGE
                else:
                    port.role  = PortRole.DESIGNATED
                port.state = PortState.FORWARDING
        else:
            # Find root port: port connected to a switch with lowest bid closer to root
            best_cost = 999999
            best_port = None
            for port_name, port_state in inst.port_states.items():
                # Look for a connected switch peer
                peer_id = self._find_connected_switch(port_name, topology)
                if peer_id and peer_id in all_switches:
                    peer_inst = all_switches[peer_id].get_instance(vlan_id)
                    if peer_inst and peer_inst.root_bridge_id == root_bid:
                        total_cost = peer_inst.root_path_cost + port_state.path_cost
                        if total_cost < best_cost:
                            best_cost = total_cost
                            best_port = port_name
                    elif peer_inst and peer_inst.bridge_id == root_bid:
                        # Direct connection to root
                        total_cost = port_state.path_cost
                        if total_cost < best_cost:
                            best_cost = total_cost
                            best_port = port_name

            inst.root_path_cost = best_cost if best_port else 0
            inst.root_port_name = best_port

            for port_name, port_state in inst.port_states.items():
                if port_state.portfast:
                    port_state.role  = PortRole.EDGE
                    port_state.state = PortState.FORWARDING
                elif port_name == best_port:
                    port_state.role  = PortRole.ROOT
                    port_state.state = PortState.FORWARDING
                else:
                    # Check if this is a designated or alternate port
                    peer_id = self._find_connected_switch(port_name, topology)
                    if peer_id is None:
                        # Edge / access port — designated
                        port_state.role  = PortRole.DESIGNATED
                        port_state.state = PortState.FORWARDING
                    else:
                        # Compare our path cost to root vs. peer's cost
                        peer_inst = all_switches.get(peer_id, None)
                        if peer_inst:
                            pi = peer_inst.get_instance(vlan_id)
                            peer_cost = (pi.root_path_cost if pi else 999999)
                        else:
                            peer_cost = 999999

                        our_cost = inst.root_path_cost + port_state.path_cost
                        if our_cost <= peer_cost:
                            # We have better or equal path — designated
                            port_state.role  = PortRole.DESIGNATED
                            port_state.state = PortState.FORWARDING
                        else:
                            # Peer has better path — alternate (blocking)
                            port_state.role  = PortRole.ALTERNATE
                            if self._mode == STPMode.RAPID_PVST:
                                port_state.state = PortState.DISCARDING
                            else:
                                port_state.state = PortState.BLOCKING

    def _find_connected_switch(self, port_name: str, topology) -> Optional[str]:
        """Return the device_id of the switch connected via port_name, or None."""
        peer = topology.neighbours(self._device_id, port_name)
        if peer is None:
            return None
        peer_device_id, _ = peer
        peer_device = topology.devices.get(peer_device_id)
        if peer_device is None:
            return None
        from simulator_core.types import DeviceModel
        if peer_device.model == DeviceModel.SWITCH:
            return peer_device_id
        return None

    # ------------------------------------------------------------------
    # Instance management
    # ------------------------------------------------------------------

    def ensure_vlan(self, vlan_id: int) -> None:
        """Make sure an STP instance exists for this VLAN."""
        self._get_or_create_instance(vlan_id)

    def _get_or_create_instance(self, vlan_id: int) -> STPInstance:
        if vlan_id not in self._instances:
            bid = BridgeID(
                priority=self._global_priority,
                sys_id_ext=vlan_id,
                mac=self._mac,
            )
            inst = STPInstance(
                vlan_id=vlan_id,
                mode=self._mode,
                bridge_id=bid,
                root_bridge_id=bid,
            )
            self._instances[vlan_id] = inst
            # Populate port_states from VLAN 1 (the reference instance) so
            # that show spanning-tree vlan <N> for newly created VLANs
            # includes all physical interfaces registered at switch init.
            # Ports that were added after init carry their own entries in
            # every existing instance already (via register_port).
            ref = self._instances.get(1)
            if ref is not None and vlan_id != 1:
                for iface_name, ref_port in ref.port_states.items():
                    if iface_name not in inst.port_states:
                        self.register_port(inst, iface_name,
                                           path_cost=ref_port.path_cost,
                                           port_id=ref_port.port_id)
        return self._instances[vlan_id]

    def register_port(
        self,
        inst: "STPInstance",
        iface_name: str,
        path_cost: Optional[int] = None,
        port_id: Optional["PortID"] = None,
    ) -> "STPPortState":
        """
        Public API to register (or retrieve) a port in an STP instance.

        This replaces the old private ``_get_or_create_port`` method.
        All callers inside and outside STPManager must use this instead.

        Parameters
        ----------
        inst:
            The ``STPInstance`` to register the port in.
        iface_name:
            Interface name, e.g. ``"Fa0/0"``.
        path_cost:
            Explicit path cost.  If ``None``, auto-detected from port type.
        port_id:
            Explicit ``PortID``.  If ``None``, the next sequential number
            within ``inst`` is used.
        """
        if iface_name not in inst.port_states:
            port_num = len(inst.port_states) + 1
            # Auto-detect path cost from port type when not supplied.
            if path_cost is None:
                from simulator_core.port_types import detect_port_type
                port_type = detect_port_type(iface_name)
                path_cost = port_type.stp_cost_short
            if port_id is None:
                port_id = PortID(priority=128, number=port_num)
            inst.port_states[iface_name] = STPPortState(
                interface_name=iface_name,
                vlan_id=inst.vlan_id,
                port_id=port_id,
                state=PortState.FORWARDING,
                role=PortRole.DESIGNATED,
                path_cost=path_cost,
            )
        return inst.port_states[iface_name]

    # Keep the private name as a thin alias so existing internal call sites
    # (set_port_priority, set_port_cost, set_portfast, etc.) still work
    # without churn.  New external callers must use register_port().
    def _get_or_create_port(
        self, inst: "STPInstance", iface_name: str
    ) -> "STPPortState":
        return self.register_port(inst, iface_name)

    # ------------------------------------------------------------------
    # Show output helpers
    # ------------------------------------------------------------------

    def show_spanning_tree(self, vlan_id: Optional[int] = None) -> str:
        """Generate 'show spanning-tree' output."""
        if vlan_id is not None:
            instances = [self._get_or_create_instance(vlan_id)]
        else:
            instances = sorted(self._instances.values(), key=lambda i: i.vlan_id)

        if not instances:
            return "% No spanning-tree instances configured."

        lines = []
        for inst in instances:
            lines += self._format_instance(inst)
            lines.append("")
        return "\n".join(lines)

    def show_spanning_tree_brief(self) -> str:
        """Generate 'show spanning-tree summary' output."""
        mode_name = {
            STPMode.PVST: "PVST+",
            STPMode.RAPID_PVST: "Rapid PVST+",
            STPMode.MST: "MST",
        }.get(self._mode, "unknown")

        lines = [
            f"Switch is in {mode_name} mode",
            f"Root bridge for: {', '.join(f'VLAN{i.vlan_id:04d}' for i in self._instances.values() if i.is_root) or 'none'}",
            "",
            "Name                   Blocking Listening Learning Forwarding STP Active",
            "---------------------- -------- --------- -------- ---------- ----------",
        ]
        for inst in sorted(self._instances.values(), key=lambda i: i.vlan_id):
            blocking = sum(1 for p in inst.port_states.values() if p.is_blocking)
            forwarding = sum(1 for p in inst.port_states.values() if p.state == PortState.FORWARDING)
            learning = sum(1 for p in inst.port_states.values() if p.state == PortState.LEARNING)
            active = len(inst.port_states)
            name = f"VLAN{inst.vlan_id:04d}"
            lines.append(
                f"{name:<22} {blocking:<8} {0:<9} {learning:<8} {forwarding:<10} {active}"
            )
        return "\n".join(lines)

    def show_spanning_tree_detail(self, iface_name: str) -> str:
        """Generate 'show spanning-tree interface <name> detail'."""
        lines = []
        for inst in sorted(self._instances.values(), key=lambda i: i.vlan_id):
            port = inst.port_states.get(iface_name)
            if port is None:
                continue
            lines.append(f"Port {iface_name} (VLAN{inst.vlan_id:04d}) of VLAN{inst.vlan_id:04d} is {port.state.value}")
            lines.append(f"   Port path cost {port.path_cost}, Port priority {port.port_id.priority if port.port_id else 128}")
            lines.append(f"   Designated root has priority {inst.root_bridge_id.bridge_priority if inst.root_bridge_id else 32768}")
            lines.append(f"   Port is {'in PortFast mode' if port.portfast else 'not in PortFast mode'}")
            if port.bpduguard:
                lines.append(f"   BPDU Guard is enabled")
            lines.append("")
        return "\n".join(lines) if lines else f"% {iface_name} not found in any STP instance."

    def _format_instance(self, inst: STPInstance) -> list[str]:
        bid = inst.bridge_id
        root_bid = inst.root_bridge_id
        mode_name = {
            STPMode.PVST: "pvst",
            STPMode.RAPID_PVST: "rapid-pvst",
            STPMode.MST: "mst",
        }.get(self._mode, "?")

        lines = [
            f"VLAN{inst.vlan_id:04d}",
            f"  Spanning tree enabled protocol {mode_name.lower()}",
        ]

        if root_bid:
            lines.append(
                f"  Root ID    Priority    {root_bid.bridge_priority}\n"
                f"             Address     {root_bid.mac}\n"
                f"             {'This bridge is the root' if inst.is_root else f'Cost       {inst.root_path_cost}'}"
            )
            if not inst.is_root and inst.root_port_name:
                lines.append(f"             Port        {inst.root_port_name}")
            lines.append(
                f"             Hello Time  {inst.timers.hello_time} sec  "
                f"Max Age {inst.timers.max_age} sec  "
                f"Forward Delay {inst.timers.forward_delay} sec"
            )
        if bid:
            lines.append(
                f"\n  Bridge ID  Priority    {bid.bridge_priority} "
                f"(priority {bid.priority} sys-id-ext {bid.sys_id_ext})\n"
                f"             Address     {bid.mac}\n"
                f"             Hello Time  {inst.timers.hello_time} sec  "
                f"Max Age {inst.timers.max_age} sec  "
                f"Forward Delay {inst.timers.forward_delay} sec"
            )
        lines.append("")
        lines.append("Interface           Role Sts Cost      Prio.Nbr Type")
        lines.append("------------------- ---- --- --------- -------- --------------------------------")
        for name, port in sorted(inst.port_states.items()):
            role_abbr = {
                PortRole.ROOT:       "Root",
                PortRole.DESIGNATED: "Desg",
                PortRole.ALTERNATE:  "Altn",
                PortRole.BACKUP:     "Back",
                PortRole.DISABLED:   "Disa",
                PortRole.EDGE:       "Desg",
            }.get(port.role, "????")
            state_abbr = {
                PortState.FORWARDING: "FWD",
                PortState.LEARNING:   "LRN",
                PortState.LISTENING:  "LIS",
                PortState.BLOCKING:   "BLK",
                PortState.DISCARDING: "DSC",
                PortState.DISABLED:   "DIS",
            }.get(port.state, "???")
            pid = f"{port.port_id.priority}.{port.port_id.number}" if port.port_id else "128.1"
            type_flags = "P2p" + (" Edge" if port.portfast else "")
            lines.append(
                f"{name:<19} {role_abbr:<4} {state_abbr:<3} {port.path_cost:<9} {pid:<8} {type_flags}"
            )
        return lines
