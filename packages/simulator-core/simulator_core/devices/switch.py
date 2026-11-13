"""
simulator_core.devices.switch
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ethernet switch — 802.1Q trunking, PVST+/RSTP, EtherChannel (LACP/PAgP).

Data-plane behaviour:
- Access ports: forward within the same VLAN only.
- Trunk ports: carry multiple VLANs with 802.1Q tagging.
  Frames on the native VLAN are sent untagged.
- EtherChannel (port-channel): multiple physical links bundled as one
  logical interface. LACP and PAgP negotiation rules are enforced.
- STP: before forwarding, the switch checks whether the port is in a
  FORWARDING state for the VLAN.

No host I/O, no sockets, no subprocess.
"""

from __future__ import annotations

import hashlib
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from simulator_core.events import (
    FrameArrival,
    FrameDropped,
    FrameTransmit,
    MACTableLearned,
    DROP_PORT_DOWN,
)
from simulator_core.frames import EthernetFrame
from simulator_core.stp import STPManager, STPMode, PortState
from simulator_core.topology import Device
from simulator_core.types import DEFAULT_VLAN, InterfaceState
from simulator_core.cdp import CDPManager

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


# ---------------------------------------------------------------------------
# EtherChannel protocol types
# ---------------------------------------------------------------------------

class EtherChannelProtocol(Enum):
    """EtherChannel negotiation protocol."""
    NONE    = "none"      # static "on" — no negotiation
    LACP    = "lacp"      # IEEE 802.3ad
    PAGP    = "pagp"      # Cisco PAgP


class EtherChannelMode(Enum):
    """Port mode within the protocol."""
    ON          = "on"           # static, always bundle
    ACTIVE      = "active"       # LACP: initiates negotiation
    PASSIVE     = "passive"      # LACP: responds only
    DESIRABLE   = "desirable"    # PAgP: initiates negotiation
    AUTO        = "auto"         # PAgP: responds only
    OFF         = "off"          # disabled


# Protocol compatibility matrix
# Returns True if the two modes can form a bundle
_LACP_COMPATIBLE = {
    (EtherChannelMode.ACTIVE,  EtherChannelMode.ACTIVE):  True,
    (EtherChannelMode.ACTIVE,  EtherChannelMode.PASSIVE): True,
    (EtherChannelMode.PASSIVE, EtherChannelMode.ACTIVE):  True,
    (EtherChannelMode.PASSIVE, EtherChannelMode.PASSIVE): False,  # both passive = no bundle
}

_PAGP_COMPATIBLE = {
    (EtherChannelMode.DESIRABLE, EtherChannelMode.DESIRABLE): True,
    (EtherChannelMode.DESIRABLE, EtherChannelMode.AUTO):       True,
    (EtherChannelMode.AUTO,      EtherChannelMode.DESIRABLE):  True,
    (EtherChannelMode.AUTO,      EtherChannelMode.AUTO):       False,  # both auto = no bundle
}


def protocols_compatible(mode_a: str, mode_b: str) -> tuple[bool, str]:
    """
    Check if two EtherChannel modes are compatible.
    Returns (is_compatible, reason_if_not).
    """
    try:
        ma = EtherChannelMode(mode_a)
        mb = EtherChannelMode(mode_b)
    except ValueError:
        return False, f"Unknown mode(s): {mode_a!r}, {mode_b!r}"

    # Static "on" — only compatible with another "on"
    if ma == EtherChannelMode.ON and mb == EtherChannelMode.ON:
        return True, ""
    if ma == EtherChannelMode.ON or mb == EtherChannelMode.ON:
        return False, "Static 'on' requires both sides to use 'on' (no negotiation protocol)."

    # LACP modes
    lacp_modes = {EtherChannelMode.ACTIVE, EtherChannelMode.PASSIVE}
    pagp_modes  = {EtherChannelMode.DESIRABLE, EtherChannelMode.AUTO}

    if ma in lacp_modes and mb in lacp_modes:
        ok = _LACP_COMPATIBLE.get((ma, mb), False)
        if not ok:
            return False, (
                f"LACP: both sides are '{mode_a}/{mode_b}'. "
                "At least one side must be 'active' to initiate negotiation."
            )
        return True, ""

    if ma in pagp_modes and mb in pagp_modes:
        ok = _PAGP_COMPATIBLE.get((ma, mb), False)
        if not ok:
            return False, (
                f"PAgP: both sides are '{mode_a}/{mode_b}'. "
                "At least one side must be 'desirable' to initiate negotiation."
            )
        return True, ""

    # Mixed protocols
    return False, (
        f"Protocol mismatch: cannot mix LACP modes ({mode_a!r}) with "
        f"PAgP modes ({mode_b!r}). Both sides must use the same protocol."
    )


# ---------------------------------------------------------------------------
# EtherChannel bundle
# ---------------------------------------------------------------------------

class PortChannelGroup:
    """
    Represents a port-channel (EtherChannel) bundle.

    Members are physical interface names; the logical port-channel
    interface is 'Port-channel<id>'.

    Protocol state:
      negotiated_up  — True when the bundle is operationally up based on
                       protocol negotiation rules (or static "on").
    """

    def __init__(self, group_id: int) -> None:
        self.group_id: int = group_id
        self.name: str = f"Port-channel{group_id}"
        self.members: list[str] = []
        self.protocol: str = "on"
        self.admin_state: str = "up"
        # Peer protocol mode — set by CLI or discovered via topology
        self._peer_protocol: Optional[str] = None

    @property
    def lacp_protocol(self) -> EtherChannelProtocol:
        """Classify which protocol family this group uses."""
        if self.protocol in ("active", "passive"):
            return EtherChannelProtocol.LACP
        if self.protocol in ("desirable", "auto"):
            return EtherChannelProtocol.PAGP
        return EtherChannelProtocol.NONE

    @property
    def is_operationally_up(self) -> bool:
        """
        True if the bundle can carry traffic.

        For 'on': always up (no negotiation).
        For LACP/PAgP: depends on compatibility with peer.
        Without a known peer, we assume up (educational default).
        """
        if self.protocol == "on":
            return True
        if self.protocol == "off":
            return False
        if self._peer_protocol is None:
            # No peer known — treat as up for educational purposes
            return True
        compatible, _ = protocols_compatible(self.protocol, self._peer_protocol)
        return compatible

    @property
    def status_flags(self) -> str:
        """Return Cisco-style status flags for show etherchannel summary."""
        if not self.members:
            return "SD"  # S=Layer2, D=down
        if self.is_operationally_up:
            return "SU"  # S=Layer2, U=in-use
        return "SD"

    @property
    def member_flags(self) -> str:
        """Flags shown next to member port names."""
        if self.is_operationally_up:
            return "P"  # P=bundled
        return "s"  # s=suspended

    def add_member(self, iface_name: str) -> None:
        if iface_name not in self.members:
            self.members.append(iface_name)

    def remove_member(self, iface_name: str) -> None:
        if iface_name in self.members:
            self.members.remove(iface_name)

    def select_egress(self, src_mac: str, dst_mac: str) -> Optional[str]:
        """
        Load-balance across active member links using XOR of MAC bytes.
        Returns the selected member interface name or None.
        """
        if not self.is_operationally_up:
            return None
        active = [m for m in self.members if m]
        if not active:
            return None
        h = int(hashlib.md5((src_mac + dst_mac).encode()).hexdigest(), 16)
        return active[h % len(active)]
        h = int(hashlib.md5((src_mac + dst_mac).encode()).hexdigest(), 16)
        return active[h % len(active)]


# ---------------------------------------------------------------------------
# Switch
# ---------------------------------------------------------------------------

class Switch:
    """
    Protocol logic for a simulated Ethernet switch.

    Features:
    - VLAN database (create, name, delete)
    - Access ports (single VLAN)
    - Trunk ports (802.1Q, multiple VLANs, native VLAN)
    - EtherChannel bundles (static, LACP, PAgP)
    - PVST+/RSTP STP integration
    - MAC learning per VLAN
    - Unicast/broadcast/unknown-unicast forwarding
    """

    def __init__(self, device: Device, simulation: "Simulation") -> None:
        self._device = device
        self._sim = simulation

        # MAC address table: (mac_value, vlan) → interface_name
        self._mac_table: dict[tuple[str, int], str] = {}

        # VLAN database: vlan_id → vlan_name
        self._vlans: dict[int, str] = {1: "default"}

        # EtherChannel groups: group_id → PortChannelGroup
        self._port_channels: dict[int, PortChannelGroup] = {}

        # Reverse mapping: member iface → group_id
        self._member_to_pc: dict[str, int] = {}

        # STP manager
        self._stp = STPManager(
            device_id=device.id,
            mac=list(device.interfaces.values())[0].mac.value
                if device.interfaces else "00:00:00:00:00:01",
        )
        # Initialise STP for VLAN 1
        self._stp.ensure_vlan(1)

        # Register all physical interfaces with STP instances.
        self._register_stp_ports()

        # CDP manager
        hostname = device.hostname if hasattr(device, "hostname") else device.id
        self.cdp_manager = CDPManager(
            device_id=device.id,
            hostname=hostname,
            capabilities="Switch",
            platform="Cisco Catalyst 2960",
        )

    # ------------------------------------------------------------------
    # STP port registration
    # ------------------------------------------------------------------

    def _register_stp_ports(self) -> None:
        """
        Register all existing physical interfaces with every STP instance.

        Called once at the end of __init__ after STPManager is created.
        SVIs (Vlan*) and loopbacks are excluded from STP.
        Uses the public STPManager.register_port() API.
        """
        port_num = 1
        for iface in self._device.interfaces.values():
            if iface.is_svi or iface.is_loopback:
                continue
            from simulator_core.stp import PortID
            pid = PortID(priority=iface.stp_port_priority, number=port_num)
            cost = iface.stp_path_cost  # None → auto-detected inside register_port
            for inst in self._stp.all_instances():
                port = self._stp.register_port(inst, iface.name,
                                               path_cost=cost, port_id=pid)
                # Explicit stp_path_cost on the interface wins over the
                # auto-detected value that register_port may have already set.
                if iface.stp_path_cost is not None:
                    port.path_cost = iface.stp_path_cost
            port_num += 1

    def register_interface_with_stp(self, iface_name: str) -> None:
        """
        Register a single interface with all existing STP instances.

        Call this after adding an interface dynamically (e.g. from CLI).
        SVIs and loopbacks are silently ignored.
        Uses the public STPManager.register_port() API.
        """
        iface = self._device.interfaces.get(iface_name)
        if iface is None or iface.is_svi or iface.is_loopback:
            return
        # Assign the next available port number.
        existing_port_nums: set[int] = set()
        for inst in self._stp.all_instances():
            for ps in inst.port_states.values():
                if ps.port_id is not None:
                    existing_port_nums.add(ps.port_id.number)
        port_num = max(existing_port_nums, default=0) + 1
        from simulator_core.stp import PortID
        pid = PortID(priority=iface.stp_port_priority, number=port_num)
        for inst in self._stp.all_instances():
            port = self._stp.register_port(inst, iface_name,
                                           path_cost=iface.stp_path_cost,
                                           port_id=pid)
            if iface.stp_path_cost is not None:
                port.path_cost = iface.stp_path_cost

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_id(self) -> str:
        return self._device.id

    @property
    def mac_table(self) -> dict[tuple[str, int], str]:
        return dict(self._mac_table)

    @property
    def vlans(self) -> dict[int, str]:
        return dict(self._vlans)

    @property
    def stp(self) -> STPManager:
        return self._stp

    @property
    def port_channels(self) -> dict[int, PortChannelGroup]:
        return dict(self._port_channels)

    # ------------------------------------------------------------------
    # VLAN management
    # ------------------------------------------------------------------

    def create_vlan(self, vlan_id: int, name: str = "") -> None:
        if not (1 <= vlan_id <= 4094):
            raise ValueError(f"VLAN ID must be 1-4094, got {vlan_id}")
        if vlan_id not in self._vlans:
            self._vlans[vlan_id] = name or f"VLAN{vlan_id:04d}"
            self._stp.ensure_vlan(vlan_id)
            self._notify_stp_change()

    def name_vlan(self, vlan_id: int, name: str) -> None:
        if vlan_id not in self._vlans:
            raise ValueError(f"VLAN {vlan_id} does not exist")
        self._vlans[vlan_id] = name

    def delete_vlan(self, vlan_id: int) -> None:
        if vlan_id == 1:
            raise ValueError("Default VLAN 1 cannot be deleted")
        if vlan_id not in self._vlans:
            raise ValueError(f"VLAN {vlan_id} does not exist")
        del self._vlans[vlan_id]
        for iface in self._device.interfaces.values():
            if iface.vlan == vlan_id:
                iface.vlan = 1
        self._notify_stp_change()

    def set_port_vlan(self, iface_name: str, vlan_id: int) -> None:
        if vlan_id not in self._vlans:
            raise ValueError(f"VLAN {vlan_id} does not exist. Create it first.")
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            raise ValueError(f"Interface {iface_name!r} not found")
        iface.vlan = vlan_id
        self._notify_stp_change()

    def get_port_vlan(self, iface_name: str) -> int:
        iface = self._device.interfaces.get(iface_name)
        return iface.vlan if iface else DEFAULT_VLAN

    def ports_in_vlan(self, vlan_id: int) -> list[str]:
        result = []
        for name, iface in self._device.interfaces.items():
            if iface.switchport_mode == "access" and iface.vlan == vlan_id:
                result.append(name)
            elif iface.switchport_mode == "trunk":
                allowed = iface.trunk_allowed_vlans
                if allowed is None or vlan_id in allowed:
                    result.append(name)
        return result

    # ------------------------------------------------------------------
    # Trunk management
    # ------------------------------------------------------------------

    def set_trunk_mode(self, iface_name: str) -> None:
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            raise ValueError(f"Interface {iface_name!r} not found")
        iface.switchport_mode = "trunk"
        if iface.trunk_allowed_vlans is None:
            iface.trunk_allowed_vlans = None   # None = all
        self._notify_stp_change()

    def set_access_mode(self, iface_name: str) -> None:
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            raise ValueError(f"Interface {iface_name!r} not found")
        iface.switchport_mode = "access"
        self._notify_stp_change()

    def set_trunk_native_vlan(self, iface_name: str, vlan_id: int) -> None:
        if vlan_id not in self._vlans:
            raise ValueError(f"VLAN {vlan_id} does not exist")
        iface = self._device.interfaces.get(iface_name)
        if iface:
            iface.trunk_native_vlan = vlan_id

    def set_trunk_allowed_vlans(
        self,
        iface_name: str,
        vlans: Optional[list[int]],
        mode: str = "set",   # "set" | "add" | "remove" | "except"
    ) -> None:
        """
        Configure allowed VLANs on a trunk.
        mode:
          set    — replace the list
          add    — add to existing
          remove — remove from existing
          except — all except the listed VLANs (stored as None with exclusions)
        """
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            raise ValueError(f"Interface {iface_name!r} not found")
        if mode == "set":
            iface.trunk_allowed_vlans = vlans  # None = all
        elif mode == "add":
            existing = iface.trunk_allowed_vlans or []
            new = list(set(existing + (vlans or [])))
            iface.trunk_allowed_vlans = sorted(new)
        elif mode == "remove":
            existing = iface.trunk_allowed_vlans or list(self._vlans.keys())
            iface.trunk_allowed_vlans = [v for v in existing if v not in (vlans or [])]
        elif mode == "except":
            all_vlans = list(self._vlans.keys())
            iface.trunk_allowed_vlans = [v for v in all_vlans if v not in (vlans or [])]
        self._notify_stp_change()

    def _is_vlan_allowed_on_trunk(self, iface_name: str, vlan_id: int) -> bool:
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            return False
        allowed = iface.trunk_allowed_vlans
        if allowed is None:
            return True   # all VLANs allowed
        return vlan_id in allowed

    def get_active_trunk_vlans(self, iface_name: str) -> list[int]:
        """Return sorted list of VLANs active on a trunk port."""
        iface = self._device.interfaces.get(iface_name)
        if iface is None or iface.switchport_mode != "trunk":
            return []
        allowed = iface.trunk_allowed_vlans
        if allowed is None:
            return sorted(self._vlans.keys())
        return sorted(v for v in allowed if v in self._vlans)

    # ------------------------------------------------------------------
    # EtherChannel management
    # ------------------------------------------------------------------

    def add_port_channel(self, group_id: int, iface_name: str,
                         protocol: str = "on") -> PortChannelGroup:
        """Add a physical interface to a port-channel group."""
        if group_id not in self._port_channels:
            self._port_channels[group_id] = PortChannelGroup(group_id)
        pc = self._port_channels[group_id]
        pc.protocol = protocol
        pc.add_member(iface_name)
        self._member_to_pc[iface_name] = group_id
        return pc

    def remove_port_channel_member(self, iface_name: str) -> None:
        """Remove a physical interface from its port-channel."""
        gid = self._member_to_pc.pop(iface_name, None)
        if gid is not None and gid in self._port_channels:
            self._port_channels[gid].remove_member(iface_name)
            if not self._port_channels[gid].members:
                del self._port_channels[gid]

    def get_port_channel_for(self, iface_name: str) -> Optional[PortChannelGroup]:
        gid = self._member_to_pc.get(iface_name)
        return self._port_channels.get(gid) if gid is not None else None

    def _get_logical_egress(self, iface_name: str,
                            src_mac: str, dst_mac: str) -> list[str]:
        """
        Resolve the actual physical interface(s) to use for egress.
        If the interface is a port-channel member, load-balance across
        active members; otherwise return the interface itself.
        """
        # Check if this interface is itself a port-channel (logical)
        for pc in self._port_channels.values():
            if pc.name == iface_name:
                selected = pc.select_egress(src_mac, dst_mac)
                return [selected] if selected else []
        return [iface_name]

    # ------------------------------------------------------------------
    # Interface admin state
    # ------------------------------------------------------------------

    def shutdown_interface(self, iface_name: str) -> None:
        """Administratively shut down an interface and trigger STP."""
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            raise ValueError(f"Interface {iface_name!r} not found")
        iface.admin_state = InterfaceState.DOWN
        self._notify_stp_change()

    def no_shutdown_interface(self, iface_name: str) -> None:
        """Bring an administratively down interface back up and trigger STP."""
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            raise ValueError(f"Interface {iface_name!r} not found")
        iface.admin_state = InterfaceState.UP
        self._notify_stp_change()

    def _notify_stp_change(self) -> None:
        """Notify the simulation that STP must be recalculated."""
        if self._sim is not None:
            self._sim._trigger_stp()

    # ------------------------------------------------------------------
    # STP configuration wrappers (delegate + notify)
    # ------------------------------------------------------------------

    def set_stp_bridge_priority(self, vlan_id: int, priority: int) -> None:
        """Set bridge priority for the given VLAN and trigger STP."""
        self._stp.set_bridge_priority(vlan_id, priority)
        self._notify_stp_change()

    def set_stp_port_cost(self, iface_name: str, vlan_id: int, cost: int) -> None:
        """Set port path cost for the given interface/VLAN and trigger STP."""
        self._stp.set_port_cost(iface_name, vlan_id, cost)
        self._notify_stp_change()

    def set_stp_port_priority(self, iface_name: str, vlan_id: int, priority: int) -> None:
        """Set port priority for the given interface/VLAN and trigger STP."""
        self._stp.set_port_priority(iface_name, vlan_id, priority)
        self._notify_stp_change()

    # ------------------------------------------------------------------
    # BPDU processing
    # ------------------------------------------------------------------

    def _process_bpdu(self, ingress_iface: str, frame: EthernetFrame) -> None:
        """
        Process a received BPDU frame on the given ingress interface.

        Architecture (Phase 2): BPDU-driven election is fully local.
        We do NOT call _trigger_stp() / _recalculate_instance_with_peers()
        here.  Root election emerges purely from BPDU priority-vector
        comparison and local recalculation from stored best-BPDUs.

        Priority vector (STP §8.4.5):
          (root_bridge_id, root_path_cost, sender_bridge_id, sender_port_id)
        Lower is better.
        """
        from simulator_core.stp import PortRole, PortState, BridgeID
        bpdu = frame.bpdu_payload
        if bpdu is None or bpdu.root_bridge_id is None or bpdu.bridge_id is None:
            return

        # Determine which VLAN instance this BPDU belongs to.
        vlan_id = bpdu.root_bridge_id.sys_id_ext or 1
        inst = self._stp.get_instance(vlan_id)
        if inst is None:
            return

        # Increment rx counter; apply BPDUFilter / BPDUGuard.
        port_state = inst.port_states.get(ingress_iface)
        if port_state is None:
            return

        # --- BPDUFilter: ignore received BPDUs on filtered ports ---
        if port_state.bpdufilter:
            return

        # --- BPDUGuard: err-disable PortFast ports on BPDU receipt ---
        if port_state.bpduguard and port_state.portfast:
            port_state.state = PortState.ERR_DISABLED
            port_state.role  = PortRole.DISABLED
            return

        port_state.bpdu_rx += 1
        # Record receipt tick for max-age expiry tracking.
        if self._sim is not None:
            port_state.last_bpdu_tick = self._sim.clock

        # --- Priority-vector comparison ---
        # Build the incoming vector: (root_bid, root_path_cost, sender_bid, sender_port_id)
        # We store the best BPDU (lowest vector) seen on each port.
        current_best = port_state.best_bpdu
        received_better = False

        if current_best is None:
            # No best_bpdu stored yet.  Only accept if this BPDU's root is
            # at least as good as the root we already know (from run_stp or
            # a previous BPDU).  This prevents an inferior first BPDU from
            # overwriting a known-good root derived from centralized election.
            if (inst.root_bridge_id is not None and
                    bpdu.root_bridge_id > inst.root_bridge_id):
                # Inferior first BPDU — ignore (keep centralized state)
                pass
            else:
                received_better = True
        else:
            # Compare root_bridge_id first
            if bpdu.root_bridge_id < current_best.root_bridge_id:
                received_better = True
            elif bpdu.root_bridge_id == current_best.root_bridge_id:
                if bpdu.root_path_cost < current_best.root_path_cost:
                    received_better = True
                elif bpdu.root_path_cost == current_best.root_path_cost:
                    if bpdu.bridge_id < current_best.bridge_id:
                        received_better = True
                    elif bpdu.bridge_id == current_best.bridge_id:
                        # Tie-break on sender port_id
                        if (bpdu.port_id is not None and
                                current_best.port_id is not None and
                                bpdu.port_id < current_best.port_id):
                            received_better = True

        if received_better:
            # --- RootGuard: check BEFORE accepting the BPDU ---
            # If the ingress port carries a RootGuard and the BPDU advertises
            # a root better than our own Bridge ID, reject the BPDU entirely —
            # do NOT store it, do NOT recalculate.  Set the port to
            # ROOT_INCONSISTENT so it stays DISCARDING until the offending
            # BPDUs age out.
            if port_state.guard == "root" and inst.bridge_id is not None:
                if bpdu.root_bridge_id < inst.bridge_id:
                    port_state.state = PortState.ROOT_INCONSISTENT
                    # Ensure any stale best_bpdu from a previous cycle is cleared.
                    port_state.best_bpdu = None
                    return   # do not store or recalculate

            port_state.best_bpdu = bpdu
            # Local recalculation from stored BPDUs — no peer inspection.
            new_learning = self._stp.recalculate_from_bpdus(inst)
            # Phase 5: schedule ForwardDelayEvents for ports entering LEARNING
            if self._sim is not None and new_learning:
                forward_delay = inst.timers.forward_delay
                for lport in new_learning:
                    self._sim.schedule_forward_delay(
                        device_id=self.device_id,
                        interface_name=lport,
                        vlan_id=vlan_id,
                        at_tick=self._sim.clock + forward_delay,
                    )

    # ------------------------------------------------------------------
    # FrameArrival handler
    # ------------------------------------------------------------------

    def handle_frame_arrival(self, event: FrameArrival) -> None:
        frame = event.frame
        ingress_iface = event.interface_name
        arrive_time = event.time

        iface = self._device.interfaces.get(ingress_iface)
        if iface is None:
            return

        # CDP frames bypass all forwarding, MAC learning, and STP checks.
        # They are never forwarded — consumed locally only.
        if frame.cdp_payload is not None:
            self.cdp_manager.update_neighbor(
                local_interface=ingress_iface,
                entry=frame.cdp_payload,
                current_tick=arrive_time,
            )
            return  # never forward CDP

        # Detect and process BPDUs before normal forwarding.
        # BPDUs bypass STP port state checks and MAC learning.
        if frame.bpdu_payload is not None:
            self._process_bpdu(ingress_iface, frame)
            return  # BPDUs are not forwarded as user frames

        # Resolve VLAN from port mode
        if iface.switchport_mode == "trunk":
            # On a trunk the frame may arrive with or without a tag.
            # In our model all frames within the simulator are conceptually
            # untagged (the VLAN is tracked via metadata).
            # We use the VLAN already associated with the frame's originating
            # access port. For frames from trunk peers, derive from context.
            # Simple approach: if the frame has no VLAN metadata we use native.
            vlan = iface.trunk_native_vlan
        else:
            vlan = iface.vlan

        # STP check: drop frames if port is not forwarding for this VLAN
        if not self._stp.is_port_forwarding(ingress_iface, vlan):
            # Port is in LEARNING state: allow MAC learning but block forwarding.
            # Port is DISCARDING/BLOCKING: drop without learning.
            if self._stp.is_port_learning_or_forwarding(ingress_iface, vlan):
                # LEARNING state: learn the source MAC but do NOT forward
                self._learn(arrive_time, frame.src_mac.value, ingress_iface, vlan)
            return

        # Learn source MAC (only in forwarding state, already checked above)
        self._learn(arrive_time, frame.src_mac.value, ingress_iface, vlan)

        # Forward
        dst_mac = frame.dst_mac.value
        if frame.dst_mac.is_broadcast:
            self._flood_in_vlan(arrive_time, frame, ingress_iface, vlan)
        else:
            known_port = self._mac_table.get((dst_mac, vlan))
            if known_port is not None and known_port != ingress_iface:
                dest_iface = self._device.interfaces.get(known_port)
                # Verify destination port is in the same VLAN
                if dest_iface and self._port_carries_vlan(known_port, vlan):
                    self._forward(arrive_time, frame, known_port,
                                  frame.src_mac.value, dst_mac,
                                  frame_vlan=vlan)
            elif known_port == ingress_iface:
                pass  # Same-port drop
            else:
                self._flood_in_vlan(arrive_time, frame, ingress_iface, vlan)

    # ------------------------------------------------------------------
    # Port VLAN membership check
    # ------------------------------------------------------------------

    def _port_carries_vlan(self, iface_name: str, vlan_id: int) -> bool:
        """True if this port should carry traffic for vlan_id."""
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            return False
        if iface.switchport_mode == "access":
            return iface.vlan == vlan_id
        elif iface.switchport_mode == "trunk":
            return self._is_vlan_allowed_on_trunk(iface_name, vlan_id)
        return False

    # ------------------------------------------------------------------
    # Forwarding internals
    # ------------------------------------------------------------------

    def _learn(self, time: int, mac_value: str,
               iface_name: str, vlan: int) -> None:
        key = (mac_value, vlan)
        if self._mac_table.get(key) != iface_name:
            self._mac_table[key] = iface_name
            seq = self._sim.next_seq()
            self._sim.schedule(MACTableLearned(
                time=time, seq=seq,
                switch_id=self.device_id,
                mac_address=mac_value,
                interface_name=iface_name,
                vlan=vlan,
            ))

    def _forward(self, time: int, frame: EthernetFrame,
                 egress_iface: str, src_mac: str, dst_mac: str,
                 frame_vlan: Optional[int] = None) -> None:
        # BPDUs bypass the STP egress forwarding check.
        if frame.bpdu_payload is None:
            # Check STP state for the egress port before forwarding user frames.
            # Use the actual frame VLAN (not the egress port's native VLAN) so
            # that a trunk DISCARDING for VLAN 10 correctly blocks VLAN 10
            # traffic even when the native VLAN is VLAN 1 (audit finding §5.4).
            iface = self._device.interfaces.get(egress_iface)
            if iface is not None:
                if frame_vlan is not None:
                    stp_vlan = frame_vlan
                elif iface.switchport_mode == "access":
                    stp_vlan = iface.vlan
                else:
                    stp_vlan = iface.trunk_native_vlan
                if not self._stp.is_port_forwarding(egress_iface, stp_vlan):
                    return  # Drop — egress port is STP discarding/blocking
        # Resolve EtherChannel if needed
        physical_ports = self._get_logical_egress(egress_iface, src_mac, dst_mac)
        for port in physical_ports:
            self._send_on_port(time, frame, port)

    def _send_on_port(self, time: int, frame: EthernetFrame,
                      egress_iface: str) -> None:
        iface = self._device.interfaces.get(egress_iface)
        if iface is None:
            return
        if iface.admin_state == InterfaceState.DOWN:
            self._sim._record(FrameDropped(
                time=time + 1, seq=self._sim.next_seq(),
                device_id=self.device_id,
                interface_name=egress_iface,
                frame=frame,
                reason=DROP_PORT_DOWN,
            ))
            return
        self._sim.schedule(FrameTransmit(
            time=time + 1, seq=self._sim.next_seq(),
            device_id=self.device_id,
            interface_name=egress_iface,
            frame=frame,
        ))

    def _flood_in_vlan(self, time: int, frame: EthernetFrame,
                       ingress_iface: str, vlan: int) -> None:
        for iface_name in self._device.interfaces:
            if iface_name == ingress_iface:
                continue
            if not self._port_carries_vlan(iface_name, vlan):
                continue
            if not self._stp.is_port_forwarding(iface_name, vlan):
                continue
            self._forward(time, frame, iface_name,
                          frame.src_mac.value, frame.dst_mac.value,
                          frame_vlan=vlan)
