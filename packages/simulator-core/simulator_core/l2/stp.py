"""
simulator_core.l2.stp
~~~~~~~~~~~~~~~~~~~~~
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

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional


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

    # Guard / security states (Phase 6)
    ERR_DISABLED      = "err-disabled"      # BPDUGuard tripped
    ROOT_INCONSISTENT = "root-inconsistent" # RootGuard tripped


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
    cost_configured: bool = False  # set by "spanning-tree [vlan N] cost"
    port_id:   Optional[PortID] = None

    # Port-fast
    portfast:   bool = False
    bpduguard:  bool = False
    bpdufilter: bool = False
    guard:      str  = "none"    # "none" | "root" | "loop"

    # Best BPDU received on this port (used for role calculation)
    best_bpdu: Optional[BPDU] = None

    # Tick at which the last BPDU was received (for max-age expiry, Phase 4)
    last_bpdu_tick: int = -1

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
                              PortState.DISABLED, PortState.ERR_DISABLED,
                              PortState.ROOT_INCONSISTENT)


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

def _port_id(port: Optional["STPPortState"]) -> "PortID":
    """A port's ID for comparisons (IOS default priority 128 when unset)."""
    if port is None or port.port_id is None:
        return PortID(priority=128, number=0)
    return port.port_id


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
        # Configured per-VLAN bridge priorities.  Kept apart from the
        # instances so "spanning-tree vlan 1-4094 priority N" does not build
        # thousands of trees: a VLAN created later picks its priority up here.
        self._vlan_priority: dict[int, int] = {}
        # While > 0, configuration changes are collected and the election
        # runs once when the outermost deferred_changes() block ends.
        self._defer_depth = 0
        self._pending_change = False

        # Per-VLAN STP instances: vlan_id → STPInstance
        self._instances: dict[int, STPInstance] = {}

        # Feature flags
        self._stp_enabled: bool = True
        self._portfast_default: bool = False    # portfast default on access ports

        # Called after any change that affects the spanning tree (priority,
        # port cost or priority, PortFast, mode).  The simulation sets it to
        # re-run the network-wide election; a stand-alone manager has none.
        self.on_change: Optional[Callable[[], None]] = None

        # PVST+: does a port carry a VLAN?  The switch sets this from its
        # VLAN database and port modes (access VLAN, trunk allowed list).
        # None (stand-alone manager) means every port carries every VLAN.
        self.port_vlan_filter: Optional[Callable[[str, int], bool]] = None

        # Set by Simulation.run_stp() for the length of one election and
        # shared by every switch: (vlan, switch) -> switches it can reach.
        # Links do not change during an election, so each search runs once.
        self.reach_cache: Optional[dict[tuple[int, str], set[str]]] = None

        # Initialize default instance for VLAN 1
        self._get_or_create_instance(1)

    def carries(self, port_name: str, vlan_id: int) -> bool:
        """True if *port_name* carries *vlan_id* (takes part in its tree)."""
        return self.port_vlan_filter is None or self.port_vlan_filter(port_name, vlan_id)

    def _vlan_ports(self, vlan_id: int, up_ports: Optional[set[str]]) -> Optional[set[str]]:
        """Up ports that carry *vlan_id*; None when *up_ports* is None (no filtering)."""
        if up_ports is None:
            return None
        return {p for p in up_ports if self.carries(p, vlan_id)}

    def _changed(self) -> bool:
        """Ask the simulation to re-run the election.  False if stand-alone."""
        if self._defer_depth:
            self._pending_change = True
            return True
        if self.on_change is None:
            return False
        self.on_change()
        return True

    @contextmanager
    def deferred_changes(self):
        """Apply several settings (a VLAN range) with a single re-election."""
        self._defer_depth += 1
        try:
            yield
        finally:
            self._defer_depth -= 1
            if not self._defer_depth and self._pending_change:
                self._pending_change = False
                if not self._changed():
                    for inst in self._instances.values():
                        self._recalculate_instance(inst)

    # ------------------------------------------------------------------
    # Configuration API
    # ------------------------------------------------------------------

    @property
    def mode(self) -> STPMode:
        return self._mode

    @mode.setter
    def mode(self, value: STPMode) -> None:
        changed = value != self._mode
        self._mode = value
        for inst in self._instances.values():
            inst.mode = value
        if changed:
            self._changed()

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
        self._remember_priority(vlan_id, priority)
        inst = self._get_or_create_instance(vlan_id)
        inst.bridge_id = BridgeID(
            priority=priority,
            sys_id_ext=vlan_id,
            mac=self._mac,
        )
        # The root can only be known network-wide; a stand-alone manager
        # (unit tests) falls back to treating itself as root.
        if not self._changed():
            self._recalculate_instance(inst)

    def _remember_priority(self, vlan_id: int, priority: int) -> None:
        if priority == self._global_priority:
            self._vlan_priority.pop(vlan_id, None)
        else:
            self._vlan_priority[vlan_id] = priority

    def store_bridge_priority(self, vlan_id: int, priority: int) -> None:
        """
        Set a VLAN's bridge priority, creating no instance for a VLAN that
        has none yet (it is applied when the VLAN's instance is created).
        """
        if vlan_id in self._instances or priority % 4096 or not 0 <= priority <= 61440:
            # Existing instance, or an invalid value (set_bridge_priority raises).
            self.set_bridge_priority(vlan_id, priority)
        else:
            self._remember_priority(vlan_id, priority)

    def configured_priorities(self) -> dict[int, int]:
        """VLAN -> bridge priority, for VLANs whose priority is not the default."""
        result = dict(self._vlan_priority)
        for vid, inst in self._instances.items():
            if inst.bridge_id is not None and inst.bridge_id.priority != self._global_priority:
                result[vid] = inst.bridge_id.priority
            elif vid in result and inst.bridge_id is not None:
                del result[vid]
        return dict(sorted(result.items()))

    def root_primary_priority(self, vlan_id: int) -> int:
        """
        Priority that ``spanning-tree vlan N root primary`` would set (IOS rule).

        24576 if that makes this switch the root; otherwise 4096 below the
        current root's priority.  Raises ValueError when even priority 0
        cannot win (the root already has priority 0 and a lower MAC).
        """
        inst = self._get_or_create_instance(vlan_id)
        root = inst.root_bridge_id
        own = inst.bridge_id
        if root is None or own is None or root == own:
            # Already root: IOS still lowers the priority to 24576.
            return min(24576, own.priority if own else 24576)
        if BridgeID(24576, vlan_id, self._mac) < root:
            return 24576
        target = (root.priority // 4096) * 4096 - 4096
        if target >= 0 and BridgeID(target, vlan_id, self._mac) < root:
            return target
        if target + 4096 >= 0 and BridgeID(target + 4096, vlan_id, self._mac) < root:
            return target + 4096
        raise ValueError(f"Failed to make the bridge root for vlan {vlan_id}")

    def set_root_primary(self, vlan_id: int) -> int:
        """Make this switch the root (IOS rule, see root_primary_priority)."""
        priority = self.root_primary_priority(vlan_id)
        self.set_bridge_priority(vlan_id, priority)
        return priority

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
        self._changed()

    def set_port_cost(self, iface_name: str, vlan_id: int, cost: int) -> None:
        """Manually set port path cost."""
        if not (1 <= cost <= 200000000):
            raise ValueError(f"Path cost must be 1-200000000, got {cost}.")
        inst = self._get_or_create_instance(vlan_id)
        port = self._get_or_create_port(inst, iface_name)
        port.path_cost = cost
        port.cost_configured = True
        self._changed()

    def set_portfast(self, iface_name: str, enabled: bool) -> None:
        """Enable or disable PortFast on an interface (all VLANs)."""
        for inst in self._instances.values():
            port = self._get_or_create_port(inst, iface_name)
            port.portfast = enabled
            if enabled:
                port.state = PortState.FORWARDING
                port.role  = PortRole.EDGE
        self._changed()

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

        MAC learning is allowed in both LEARNING and FORWARDING states per
        IEEE 802.1D.  In the BPDU-driven simulation path (Phase 5), ports
        enter LEARNING before transitioning to FORWARDING after the configured
        forward_delay.  PortFast/EDGE ports skip LEARNING and go directly to
        FORWARDING.  This method returns True for both states so that MAC
        learning is correctly permitted during the LEARNING interval.

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

    def recalculate_from_bpdus(self, inst: "STPInstance") -> list[str]:
        """
        Local-only recalculation using stored best-BPDUs on each port.

        This is the BPDU-driven election path (Phase 2).  It does NOT read
        any peer STPManager object — it uses only:
          - Our own bridge_id
          - port.best_bpdu stored on each port

        Algorithm:
        1. Find the port whose best_bpdu has the lowest priority vector
           (root_bid, root_path_cost + local_cost, sender_bid, sender_port_id).
           That port becomes the Root Port.
        2. Update inst.root_bridge_id / root_path_cost / root_port_name.
        3. Assign DESIGNATED to remaining ports with no competing best_bpdu or
           where our cost is ≤ peer's advertised cost.
        4. Assign ALTERNATE to remaining ports.
        5. Never assigns roles that require reading peer STPManager objects.

        Phase 5: ports that transition from DISCARDING/BLOCKING to ROOT or
        DESIGNATED are set to LEARNING first (not FORWARDING), unless they
        are PortFast/EDGE.  Returns the list of interface names that entered
        LEARNING so the caller can schedule ForwardDelayEvents.
        """
        if inst.bridge_id is None:
            return []

        own_bid = inst.bridge_id

        # Snapshot current states to detect transitions (Phase 5)
        prev_states = {pname: ps.state for pname, ps in inst.port_states.items()}

        # Collect candidate (port_name, root_bid, total_cost, sender_bid, sender_port_id)
        # for each port that has a best_bpdu with a root better than ourselves.
        candidates: list[tuple] = []
        for pname, ps in inst.port_states.items():
            if ps.best_bpdu is None:
                continue
            bpdu = ps.best_bpdu
            if bpdu.root_bridge_id is None:
                continue
            # Only consider BPDUs that advertise a root better than us
            if bpdu.root_bridge_id >= own_bid:
                continue
            total_cost = bpdu.root_path_cost + ps.path_cost
            sender_port_id = bpdu.port_id.value if bpdu.port_id else 0xFFFF
            # Priority vector for root-port election
            candidates.append((
                bpdu.root_bridge_id,
                total_cost,
                bpdu.bridge_id,
                sender_port_id,
                pname,
            ))

        new_learning_ports: list[str] = []

        if not candidates:
            # No better root found in BPDUs — we are (or remain) root
            inst.root_bridge_id = own_bid
            inst.root_path_cost = 0
            inst.root_port_name = None
            for pname, ps in inst.port_states.items():
                if ps.portfast:
                    ps.role  = PortRole.EDGE
                    ps.state = PortState.FORWARDING
                elif ps.state not in (PortState.ERR_DISABLED,
                                      PortState.ROOT_INCONSISTENT):
                    ps.role  = PortRole.DESIGNATED
                    # Phase 5: LEARNING transition for ports coming out of block
                    old = prev_states.get(pname, PortState.FORWARDING)
                    if old in (PortState.DISCARDING, PortState.BLOCKING,
                               PortState.DISABLED):
                        ps.state = PortState.LEARNING
                        new_learning_ports.append(pname)
                    else:
                        ps.state = PortState.FORWARDING
            return new_learning_ports

        # Elect root port: sort by priority vector (all elements comparable)
        candidates.sort()
        best = candidates[0]
        root_bid, root_cost, _sender_bid, _sender_pid, root_port_name = best

        inst.root_bridge_id = root_bid
        inst.root_path_cost = root_cost
        inst.root_port_name = root_port_name

        # Assign roles
        for pname, ps in inst.port_states.items():
            if ps.state in (PortState.ERR_DISABLED, PortState.ROOT_INCONSISTENT):
                continue
            if ps.portfast:
                ps.role  = PortRole.EDGE
                ps.state = PortState.FORWARDING
            elif pname == root_port_name:
                ps.role  = PortRole.ROOT
                old = prev_states.get(pname, PortState.FORWARDING)
                if old in (PortState.DISCARDING, PortState.BLOCKING,
                           PortState.DISABLED):
                    # Phase 5: new root port enters LEARNING
                    ps.state = PortState.LEARNING
                    new_learning_ports.append(pname)
                else:
                    ps.state = PortState.FORWARDING
            elif ps.best_bpdu is not None:
                # Another port with a best_bpdu: compare our advertised cost
                # to the sender's root_path_cost.
                peer_bpdu = ps.best_bpdu
                our_cost = root_cost  # our total cost to root
                peer_cost = peer_bpdu.root_path_cost
                if our_cost <= peer_cost:
                    ps.role  = PortRole.DESIGNATED
                    old = prev_states.get(pname, PortState.FORWARDING)
                    if old in (PortState.DISCARDING, PortState.BLOCKING,
                               PortState.DISABLED):
                        ps.state = PortState.LEARNING
                        new_learning_ports.append(pname)
                    else:
                        ps.state = PortState.FORWARDING
                else:
                    ps.role  = PortRole.ALTERNATE
                    if self._mode == STPMode.RAPID_PVST:
                        ps.state = PortState.DISCARDING
                    else:
                        ps.state = PortState.BLOCKING
            else:
                # No best_bpdu — no competing switch on this segment
                ps.role  = PortRole.DESIGNATED
                old = prev_states.get(pname, PortState.FORWARDING)
                if old in (PortState.DISCARDING, PortState.BLOCKING,
                           PortState.DISABLED):
                    ps.state = PortState.LEARNING
                    new_learning_ports.append(pname)
                else:
                    ps.state = PortState.FORWARDING

        return new_learning_ports

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

        # Only switches this one can reach over up links take part (a
        # switch cut off from the rest of the network elects its own root).
        reachable = self._reachable_switches(topology, all_switches, vlan_id)
        all_bids: list[BridgeID] = [inst.bridge_id]
        for peer_id in reachable:
            peer_inst = all_switches[peer_id].get_instance(vlan_id)
            if peer_inst and peer_inst.bridge_id:
                all_bids.append(peer_inst.bridge_id)

        # Elect root: lowest bridge ID wins
        root_bid = min(all_bids)
        inst.root_bridge_id = root_bid
        is_root = (root_bid == inst.bridge_id)

        def peer_of(port_name: str):
            """(peer STPInstance, peer port state) across an up link, or None."""
            peer = self._vlan_peer(port_name, vlan_id, topology, all_switches)
            if peer is None:
                return None
            peer_inst = all_switches[peer[0]].get_instance(vlan_id)
            if peer_inst is None:
                return None
            return peer_inst, peer_inst.port_states.get(peer[1])

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
            return

        # Root port: lowest (root path cost, sender bridge ID, sender port
        # ID, own port ID) among ports whose neighbour already agrees on the
        # root -- the 802.1D priority vector.
        best_key = None
        best_port = None
        for port_name, port_state in inst.port_states.items():
            peer = peer_of(port_name)
            if peer is None:
                continue
            peer_inst, peer_port = peer
            if peer_inst.root_bridge_id != root_bid:
                continue
            key = (
                peer_inst.root_path_cost + port_state.path_cost,
                peer_inst.bridge_id,
                _port_id(peer_port),
                _port_id(port_state),
            )
            if best_key is None or key < best_key:
                best_key, best_port = key, port_name

        inst.root_path_cost = best_key[0] if best_key else 0
        inst.root_port_name = best_port

        for port_name, port_state in inst.port_states.items():
            if port_state.portfast:
                port_state.role  = PortRole.EDGE
                port_state.state = PortState.FORWARDING
                continue
            if port_name == best_port:
                port_state.role  = PortRole.ROOT
                port_state.state = PortState.FORWARDING
                continue
            peer = peer_of(port_name)
            if peer is None:
                # Edge / access port, or not up -- designated
                port_state.role  = PortRole.DESIGNATED
                port_state.state = PortState.FORWARDING
                continue
            peer_inst, peer_port = peer
            # Designated port for the segment: the side advertising the
            # better (root path cost, bridge ID, port ID).
            ours = (inst.root_path_cost, inst.bridge_id, _port_id(port_state))
            theirs = (
                peer_inst.root_path_cost if peer_inst.root_bridge_id == root_bid else 999999,
                peer_inst.bridge_id,
                _port_id(peer_port),
            )
            if ours < theirs:
                port_state.role  = PortRole.DESIGNATED
                port_state.state = PortState.FORWARDING
            else:
                # Peer has the better path -- alternate (blocking)
                port_state.role  = PortRole.ALTERNATE
                if self._mode == STPMode.RAPID_PVST:
                    port_state.state = PortState.DISCARDING
                else:
                    port_state.state = PortState.BLOCKING

    def reset_election(self) -> None:
        """Forget the last election (each switch believes it is the root)."""
        for inst in self._instances.values():
            inst.root_bridge_id = inst.bridge_id
            inst.root_path_cost = 0
            inst.root_port_name = None

    def _vlan_peer(self, port_name: str, vlan_id: int, topology,
                   all_switches: dict[str, "STPManager"]) -> Optional[tuple[str, str]]:
        """
        (switch id, port) across an up link on which both ends carry
        *vlan_id* -- the link is part of that VLAN's spanning tree.
        """
        if not self.carries(port_name, vlan_id):
            return None
        peer = self._find_connected_switch_port(port_name, topology)
        if peer is None or peer[0] not in all_switches:
            return None
        if not all_switches[peer[0]].carries(peer[1], vlan_id):
            return None
        return peer

    def _reachable_switches(self, topology, all_switches: dict[str, "STPManager"],
                            vlan_id: int) -> set[str]:
        """Other switches reachable over up links that carry *vlan_id*."""
        cache = self.reach_cache
        if cache is not None and (vlan_id, self._device_id) in cache:
            return cache[(vlan_id, self._device_id)]
        seen = {self._device_id}
        queue = [self._device_id]
        while queue:
            current = all_switches.get(queue.pop())
            if current is None:
                continue
            device = topology.devices.get(current._device_id)
            if device is None:
                continue
            for name in device.interfaces:
                peer = current._vlan_peer(name, vlan_id, topology, all_switches)
                if peer and peer[0] not in seen:
                    seen.add(peer[0])
                    queue.append(peer[0])
        if cache is not None:
            # Everyone in the component reaches the same set of switches.
            for member in seen:
                cache[(vlan_id, member)] = seen - {member}
        seen.discard(self._device_id)
        return seen

    def _is_port_admin_down(self, port_name: str, topology) -> bool:
        """Return True if this port's interface is administratively down."""
        device = topology.devices.get(self._device_id)
        if device is None:
            return False
        iface = device.interfaces.get(port_name)
        if iface is None:
            return False
        from simulator_core.types import InterfaceState
        return iface.admin_state == InterfaceState.DOWN

    def _find_connected_switch_port(self, port_name: str, topology) -> Optional[tuple[str, str]]:
        """
        (switch id, its port) at the far end of *port_name*, when the link is
        up (both ports cabled and enabled).  None for hosts, routers and
        down or unplugged ports, which do not take part in STP.
        """
        from simulator_core.types import DeviceModel, InterfaceState
        device = topology.devices.get(self._device_id)
        iface = device.interfaces.get(port_name) if device else None
        def down(i) -> bool:
            return (i is None or i.oper_state != InterfaceState.UP
                    or i.admin_state == InterfaceState.DOWN)
        if down(iface):
            return None
        if iface.is_port_channel:
            # A port-channel faces the port-channel its bundled members
            # lead to; it is one port for spanning tree.
            gid = iface.name[2:]
            for name, member in device.interfaces.items():
                if str(member.channel_group) != gid or member.ec_state != "P":
                    continue
                peer = topology.neighbours(self._device_id, name)
                peer_device = topology.devices.get(peer[0]) if peer else None
                peer_member = peer_device.interfaces.get(peer[1]) if peer_device else None
                if (peer_member is not None and peer_member.ec_state == "P"
                        and peer_device.model == DeviceModel.SWITCH):
                    po = f"Po{peer_member.channel_group}"
                    if not down(peer_device.interfaces.get(po)):
                        return peer[0], po
            return None
        if iface.in_bundle:
            return None             # represented by its port-channel
        peer = topology.neighbours(self._device_id, port_name)
        if peer is None:
            return None
        peer_device = topology.devices.get(peer[0])
        if peer_device is None or peer_device.model != DeviceModel.SWITCH:
            return None
        peer_iface = peer_device.interfaces.get(peer[1])
        if down(peer_iface) or peer_iface.in_bundle:
            return None
        return peer[0], peer[1]

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
                priority=self._vlan_priority.get(vlan_id, self._global_priority),
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

    def unregister_port(self, iface_name: str) -> None:
        """Forget a port in every instance (a deleted port-channel)."""
        for inst in self._instances.values():
            inst.port_states.pop(iface_name, None)

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

    def show_spanning_tree(self, vlan_id: Optional[int] = None,
                           active_ports: Optional[set] = None) -> str:
        """
        Generate 'show spanning-tree' output.

        *active_ports*, when given, limits the port table to those ports
        (IOS lists only ports whose line protocol is up).
        """
        if vlan_id is not None:
            inst = self._instances.get(vlan_id)
            instances = [inst] if inst is not None else []
        else:
            instances = sorted(self._instances.values(), key=lambda i: i.vlan_id)

        # Like IOS, a VLAN's instance is shown only while at least one up
        # port carries that VLAN.
        shown = []
        for inst in instances:
            ports = self._vlan_ports(inst.vlan_id, active_ports)
            if ports is None or ports:
                shown.append((inst, ports))

        if not shown:
            if vlan_id is not None:
                return f"Spanning tree instance(s) for vlan {vlan_id} does not exist."
            return "No spanning tree instance exists."

        lines = []
        for inst, ports in shown:
            lines += self._format_instance(inst, ports)
            lines.append("")
        return "\n".join(lines)

    def show_spanning_tree_brief(self, active_ports: Optional[set[str]] = None) -> str:
        """
        Generate 'show spanning-tree summary' output.

        Like IOS, only ports that are up are counted; *active_ports* is that
        set (None counts every registered port, for stand-alone use).
        """
        def counted(inst: STPInstance) -> list[STPPortState]:
            ports = self._vlan_ports(inst.vlan_id, active_ports)
            return [p for n, p in inst.port_states.items() if ports is None or n in ports]

        # Only VLANs with at least one up port carrying them are listed.
        instances = [i for i in sorted(self._instances.values(), key=lambda i: i.vlan_id)
                     if active_ports is None or counted(i)]
        root_for = [f"VLAN{i.vlan_id:04d}" for i in instances if i.is_root]
        portfast = "enabled" if self._portfast_default else "disabled"
        rule = "---------------------- -------- --------- -------- ---------- ----------"
        lines = [
            f"Switch is in {self._mode.value} mode",
            f"Root bridge for: {', '.join(root_for) or 'none'}",
            "Extended system ID           is enabled",
            f"Portfast Default             is {portfast}",
            "",
            "Name                   Blocking Listening Learning Forwarding STP Active",
            rule,
        ]
        totals = [0, 0, 0, 0, 0]
        for inst in instances:
            ports = counted(inst)
            row = [
                sum(1 for p in ports if p.is_blocking),
                sum(1 for p in ports if p.state == PortState.LISTENING),
                sum(1 for p in ports if p.state == PortState.LEARNING),
                sum(1 for p in ports if p.state == PortState.FORWARDING),
                len(ports),
            ]
            totals = [a + b for a, b in zip(totals, row)]
            lines.append(f"{f'VLAN{inst.vlan_id:04d}':<22} {row[0]:>8} {row[1]:>9} {row[2]:>8} {row[3]:>10} {row[4]:>10}")
        lines.append(rule)
        label = f"{len(instances)} vlan{'s' if len(instances) != 1 else ''}"
        lines.append(f"{label:<22} {totals[0]:>8} {totals[1]:>9} {totals[2]:>8} {totals[3]:>10} {totals[4]:>10}")
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

    def _format_instance(self, inst: STPInstance,
                         active_ports: Optional[set] = None) -> list[str]:
        bid = inst.bridge_id
        root_bid = inst.root_bridge_id
        mode_name = {
            STPMode.PVST: "ieee",
            STPMode.RAPID_PVST: "rstp",
            STPMode.MST: "mstp",
        }.get(self._mode, "?")

        lines = [
            f"VLAN{inst.vlan_id:04d}",
            f"  Spanning tree enabled protocol {mode_name.lower()}",
        ]

        if root_bid:
            lines.append(
                f"  Root ID    Priority    {root_bid.bridge_priority}\n"
                f"             Address     {_dotted_mac(root_bid.mac)}\n"
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
                f"             Address     {_dotted_mac(bid.mac)}\n"
                f"             Hello Time  {inst.timers.hello_time} sec  "
                f"Max Age {inst.timers.max_age} sec  "
                f"Forward Delay {inst.timers.forward_delay} sec"
            )
        lines.append("")
        lines.append("Interface           Role Sts Cost      Prio.Nbr Type")
        lines.append("------------------- ---- --- --------- -------- --------------------------------")
        for name, port in sorted(inst.port_states.items(),
                                 key=lambda kv: _port_sort_key(kv[0])):
            if active_ports is not None and name not in active_ports:
                continue
            role_abbr = {
                PortRole.ROOT:       "Root",
                PortRole.DESIGNATED: "Desg",
                PortRole.ALTERNATE:  "Altn",
                PortRole.BACKUP:     "Back",
                PortRole.DISABLED:   "Disa",
                PortRole.EDGE:       "Desg",
            }.get(port.role, "????")
            state_abbr = {
                PortState.FORWARDING:        "FWD",
                PortState.LEARNING:          "LRN",
                PortState.LISTENING:         "LIS",
                PortState.BLOCKING:          "BLK",
                PortState.DISCARDING:        "BLK",   # IOS prints BLK for RSTP discarding too
                PortState.DISABLED:          "DIS",
                PortState.ERR_DISABLED:      "ERR",
                PortState.ROOT_INCONSISTENT: "RIN",
            }.get(port.state, "???")
            pid = f"{port.port_id.priority}.{port.port_id.number}" if port.port_id else "128.1"
            type_flags = "P2p" + (" Edge" if port.portfast else "")
            lines.append(
                f"{name:<19} {role_abbr:<4} {state_abbr:<3} {port.path_cost:<9} {pid:<8} {type_flags}"
            )
        return lines


def _port_sort_key(name: str) -> tuple:
    """Natural port order: Fa0/2 before Fa0/10 (IOS lists ports numerically)."""
    import re
    return tuple(int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name))


def _dotted_mac(mac) -> str:
    """Cisco notation for show output: aa:bb:cc:dd:ee:ff -> aabb.ccdd.eeff."""
    raw = str(mac).replace(":", "").replace("-", "").replace(".", "").lower()
    if len(raw) != 12:
        return str(mac)
    return f"{raw[0:4]}.{raw[4:8]}.{raw[8:12]}"
