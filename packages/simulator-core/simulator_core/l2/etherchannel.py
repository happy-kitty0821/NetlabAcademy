"""
simulator_core.l2.etherchannel
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
EtherChannel (port-channel) bundles on Catalyst switches.

A bundle is configured with ``channel-group N mode <mode>`` on member ports
and appears as the logical interface ``PoN`` (Port-channelN).  On every
interface refresh, :func:`negotiate` decides each member's state, as shown
by ``show etherchannel summary``:

====  ==========================================================================
P     bundled: the cable leads to a compatible partner in the same neighbour
      bundle; traffic and spanning tree use ``PoN`` instead of the port
I     stand-alone: LACP / PAgP found no partner, the port works on its own
s     suspended: its configuration differs from the port-channel's
D     down
====  ==========================================================================

Negotiation rules (per member, against the cable's far end):

- ``on`` bundles without a protocol.  Facing a port that is not ``on``
  is a misconfiguration: spanning tree's EtherChannel guard err-disables
  the members (``channel-misconfig``), as on IOS.
- LACP: ``active``/``passive``, at least one side ``active``.
- PAgP: ``desirable``/``auto``, at least one side ``desirable``.

Configuration entered on ``interface port-channel N`` is pushed to every
member (as IOS does); a member changed on its own afterwards no longer
matches and is suspended with ``%EC-5-CANNOT_BUNDLE2``.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import TYPE_CHECKING, Optional

from simulator_core.types import DeviceModel, InterfaceState

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation

MAX_GROUP = 6                                    # Catalyst 2960: groups 1-6
LACP_MODES = ("active", "passive")
PAGP_MODES = ("desirable", "auto")
CHANNEL_MODES = ("on",) + LACP_MODES + PAGP_MODES
LOAD_BALANCE_METHODS = ("dst-ip", "dst-mac", "src-dst-ip", "src-dst-mac", "src-ip", "src-mac")
DEFAULT_LOAD_BALANCE = "src-mac"


# ── protocol families and compatibility ───────────────────────────────────────

class EtherChannelProtocol(Enum):
    """EtherChannel negotiation protocol."""
    NONE = "none"      # static "on" — no negotiation
    LACP = "lacp"      # IEEE 802.3ad
    PAGP = "pagp"      # Cisco PAgP


class EtherChannelMode(Enum):
    """Port mode within the protocol."""
    ON = "on"
    ACTIVE = "active"
    PASSIVE = "passive"
    DESIRABLE = "desirable"
    AUTO = "auto"
    OFF = "off"


def protocol_of(mode: Optional[str]) -> EtherChannelProtocol:
    if mode in LACP_MODES:
        return EtherChannelProtocol.LACP
    if mode in PAGP_MODES:
        return EtherChannelProtocol.PAGP
    return EtherChannelProtocol.NONE


def protocol_label(mode: Optional[str]) -> str:
    """Protocol column of ``show etherchannel summary``."""
    return {EtherChannelProtocol.LACP: "LACP", EtherChannelProtocol.PAGP: "PAgP"}.get(
        protocol_of(mode), "-")


def protocols_compatible(mode_a: str, mode_b: Optional[str]) -> tuple[bool, str]:
    """Can a port in *mode_a* bundle with a partner port in *mode_b*?"""
    if mode_a not in CHANNEL_MODES:
        return False, f"Unknown mode {mode_a!r}"
    if mode_b is None:
        return False, "The partner port is not in a channel group."
    if mode_a == "on" or mode_b == "on":
        if mode_a == mode_b == "on":
            return True, ""
        return False, "Static 'on' requires both sides to use 'on' (no negotiation protocol)."
    if protocol_of(mode_a) != protocol_of(mode_b):
        return False, (f"Protocol mismatch: {protocol_label(mode_a)} on one side, "
                       f"{protocol_label(mode_b)} on the other.")
    if mode_a in LACP_MODES and "active" not in (mode_a, mode_b):
        return False, "LACP: at least one side must be 'active' (passive + passive never bundles)."
    if mode_a in PAGP_MODES and "desirable" not in (mode_a, mode_b):
        return False, "PAgP: at least one side must be 'desirable' (auto + auto never bundles)."
    return True, ""


# ── the bundle ────────────────────────────────────────────────────────────────

class PortChannelGroup:
    """
    One EtherChannel: its member ports and the state decided by
    :func:`negotiate`.  The logical interface is ``self.short`` (``Po1``).
    """

    def __init__(self, group_id: int) -> None:
        self.group_id: int = group_id
        self.name: str = f"Port-channel{group_id}"
        self.short: str = f"Po{group_id}"
        self.members: list[str] = []
        self.protocol: str = "on"               # mode of the group's members
        self.member_state: dict[str, str] = {}  # port -> P / I / s / D
        self.suspend_reason: dict[str, str] = {}
        self.synced: Optional[tuple] = None     # Po L2 config last pushed to members
        self.created_at: float = 0.0
        self.last_bundled: Optional[tuple[str, float]] = None

    # -- membership ----------------------------------------------------------
    def add_member(self, iface_name: str) -> None:
        if iface_name not in self.members:
            self.members.append(iface_name)

    def remove_member(self, iface_name: str) -> None:
        if iface_name in self.members:
            self.members.remove(iface_name)
        self.member_state.pop(iface_name, None)
        self.suspend_reason.pop(iface_name, None)

    # -- state -----------------------------------------------------------------
    @property
    def lacp_protocol(self) -> EtherChannelProtocol:
        return protocol_of(self.protocol)

    @property
    def bundled(self) -> list[str]:
        return [m for m in self.members if self.member_state.get(m) == "P"]

    @property
    def is_operationally_up(self) -> bool:
        return bool(self.bundled)

    @property
    def status_flags(self) -> str:
        """Group flags in ``show etherchannel summary``: S = layer 2, U/D."""
        return "SU" if self.bundled else "SD"

    def member_flag(self, port: str) -> str:
        return self.member_state.get(port, "D")

    # -- load balancing --------------------------------------------------------
    def select_egress(self, src_mac: str, dst_mac: str, method: str = DEFAULT_LOAD_BALANCE,
                      src_ip: Optional[str] = None, dst_ip: Optional[str] = None) -> Optional[str]:
        """
        The member a frame leaves on: a hash of the addresses the
        load-balance method uses (IP methods fall back to MACs for frames
        without an IP header).  The same flow always takes the same link.
        """
        active = self.bundled if self.member_state else list(self.members)
        if not active:
            return None
        use_ip = method.endswith("-ip") and src_ip and dst_ip
        src = src_ip if use_ip else src_mac
        dst = dst_ip if use_ip else dst_mac
        if method.startswith("src-dst"):
            key = src + dst
        elif method.startswith("dst"):
            key = dst
        else:
            key = src
        h = int(hashlib.md5(key.encode()).hexdigest(), 16)
        return active[h % len(active)]


def port_channel_mac(device_id: str, name: str):
    """Stable MAC for a port-channel interface (same in every process)."""
    import random
    from simulator_core.addresses import MACAddress
    seed = int(hashlib.md5(f"{device_id}/{name}".encode()).hexdigest(), 16) % (2 ** 31)
    return MACAddress.generate(random.Random(seed))


# ── configuration consistency ─────────────────────────────────────────────────

def l2_config(iface) -> tuple:
    """The layer 2 settings a port-channel and its members must share."""
    allowed = None if iface.trunk_allowed_vlans is None else tuple(sorted(iface.trunk_allowed_vlans))
    return (iface.switchport_mode, iface.vlan, iface.trunk_native_vlan, allowed,
            iface.dtp_nonegotiate)


def copy_l2_config(src, dst) -> None:
    dst.switchport_mode = src.switchport_mode
    dst.vlan = src.vlan
    dst.trunk_native_vlan = src.trunk_native_vlan
    dst.trunk_allowed_vlans = (None if src.trunk_allowed_vlans is None
                               else list(src.trunk_allowed_vlans))
    dst.dtp_nonegotiate = src.dtp_nonegotiate


def mismatch_reason(member, po, member_name: str, po_name: str) -> Optional[str]:
    """IOS reason text for %EC-5-CANNOT_BUNDLE2, or None if compatible."""
    def mode_word(i) -> str:
        return {"dynamic_auto": "dynamic", "dynamic_desirable": "dynamic"}.get(
            i.switchport_mode, i.switchport_mode)
    if member.switchport_mode != po.switchport_mode:
        return f"trunk mode of {member_name} is {mode_word(member)}, {po_name} is {mode_word(po)}"
    if member.is_access and member.vlan != po.vlan:
        return f"access vlan of {member_name} is {member.vlan}, {po_name} id {po.vlan}"
    if member.trunk_native_vlan != po.trunk_native_vlan:
        return (f"native vlan of {member_name} is {member.trunk_native_vlan}, "
                f"{po_name} id {po.trunk_native_vlan}")
    if l2_config(member)[3] != l2_config(po)[3]:
        return "vlan mask is different"
    if member.dtp_nonegotiate != po.dtp_nonegotiate:
        return "nonegotiate of the two ports differs"
    return None


# ── STP cost of a bundle ──────────────────────────────────────────────────────

# IEEE 802.1D short path costs Catalyst IOS gives aggregated bandwidth (Mbps).
_AGGREGATE_COST = [(10_000, 2), (2_000, 3), (1_000, 4), (800, 5), (600, 6), (500, 7),
                   (400, 8), (300, 9), (200, 12), (100, 19), (10, 100)]


def bundle_cost(total_mbps: int) -> int:
    for floor, cost in _AGGREGATE_COST:
        if total_mbps >= floor:
            return cost
    return 100


# ── negotiation (called from Simulation._compute_oper_states) ─────────────────

def negotiate(sim: "Simulation") -> None:
    """
    Decide every member's bundling state and every port-channel's
    operational state; push port-channel configuration to members; log
    bundle changes.  Physical oper states must already be computed.
    """
    topo = sim.topology
    previous: dict[tuple[str, int], dict[str, str]] = {}
    for dev_id, switch in sim._switches.items():
        device = topo.devices[dev_id]
        for gid, pc in switch._port_channels.items():
            po = device.interfaces.get(pc.short)
            if po is None:
                continue
            # Port-channel configuration changed: members follow it.
            if pc.synced != l2_config(po):
                for m in pc.members:
                    if m in device.interfaces:
                        copy_l2_config(po, device.interfaces[m])
                pc.synced = l2_config(po)

            previous[(dev_id, gid)] = dict(pc.member_state)
            state: dict[str, str] = {}
            partner: dict[str, tuple] = {}
            for m in pc.members:
                iface = device.interfaces.get(m)
                if (iface is None or iface.oper_state != InterfaceState.UP
                        or po.admin_state == InterfaceState.DOWN):
                    state[m] = "D"
                    continue
                reason = mismatch_reason(iface, po, m, pc.short)
                if reason:
                    if pc.suspend_reason.get(m) != reason:
                        sim.log_event(dev_id, "EC", 5, "CANNOT_BUNDLE2",
                                      f"{m} is not compatible with {pc.short} and will be "
                                      f"suspended ({reason})")
                    pc.suspend_reason[m] = reason
                    state[m] = "s"
                    continue
                pc.suspend_reason.pop(m, None)
                peer = topo.neighbours(dev_id, m)
                peer_dev = topo.devices.get(peer[0]) if peer else None
                peer_iface = peer_dev.interfaces.get(peer[1]) if peer_dev else None
                peer_mode = None
                if (peer_dev is not None and peer_dev.model == DeviceModel.SWITCH
                        and peer_iface is not None and peer_iface.channel_group is not None):
                    peer_mode = peer_iface.channel_mode
                if iface.channel_mode == "on":
                    state[m] = "P"                 # bundles unilaterally (see apply_guard)
                elif protocols_compatible(iface.channel_mode, peer_mode)[0]:
                    state[m] = "P"
                else:
                    state[m] = "I"
                if state[m] == "P" and peer_iface is not None and peer_iface.channel_group is not None:
                    partner[m] = (peer[0], peer_iface.channel_group)
            # All bundled members must lead to the same neighbour bundle.
            first = next((partner[m] for m in pc.members if m in partner), None)
            for m in pc.members:
                if state.get(m) == "P" and m in partner and partner[m] != first:
                    state[m] = "I"
            pc.member_state = state

    # Second pass: a protocol member whose partner did not bundle (it is
    # suspended or down on the far side) cannot stay in the bundle.
    for dev_id, switch in sim._switches.items():
        for pc in switch._port_channels.values():
            for m in pc.bundled:
                iface = topo.devices[dev_id].interfaces[m]
                if iface.channel_mode == "on":
                    continue
                peer = topo.neighbours(dev_id, m)
                peer_switch = sim._switches.get(peer[0]) if peer else None
                peer_pc = peer_switch.get_port_channel_for(peer[1]) if peer_switch else None
                if peer_pc is None or peer_pc.member_state.get(peer[1]) != "P":
                    pc.member_state[m] = "I"

    # Final states: log what changed, then bring port-channels up or down
    # (up while any member is bundled).
    for dev_id, switch in sim._switches.items():
        device = topo.devices[dev_id]
        for gid, pc in switch._port_channels.items():
            before = previous.get((dev_id, gid), {})
            for m in pc.members:
                was, now = before.get(m), pc.member_state.get(m)
                if now == "P" and was != "P":
                    sim.log_event(dev_id, "EC", 5, "BUNDLE",
                                  f"Interface {m} joined port-channel {pc.short}")
                    pc.last_bundled = (m, sim.lab_time)
                elif was == "P" and now != "P":
                    sim.log_event(dev_id, "EC", 5, "UNBUNDLE",
                                  f"Interface {m} left the port-channel {pc.short}")
            for m in pc.members:
                if m in device.interfaces:
                    device.interfaces[m].ec_state = pc.member_state.get(m, "D")
            po = device.interfaces.get(pc.short)
            if po is None:
                continue
            bundled = pc.bundled
            up = bool(bundled) and po.admin_state == InterfaceState.UP
            po.oper_state = InterfaceState.UP if up else InterfaceState.DOWN
            total_kbps = sum((device.interfaces[m].speed_kbps or 0) for m in bundled)
            po.speed_kbps = total_kbps or None
            cost = bundle_cost(total_kbps // 1000) if total_kbps else 4
            for inst in switch.stp.all_instances():
                ps = inst.port_states.get(pc.short)
                if ps is not None and not ps.cost_configured:
                    ps.path_cost = cost


def apply_guard(sim: "Simulation") -> bool:
    """
    Spanning tree's EtherChannel guard: an ``on`` bundle facing ports that
    are not in an ``on`` channel would loop, so its members are
    err-disabled (``channel-misconfig``).  Returns True if any were.
    """
    tripped = False
    topo = sim.topology
    for dev_id, switch in sim._switches.items():
        for pc in switch._port_channels.values():
            bad = []
            for m in pc.bundled:
                iface = topo.devices[dev_id].interfaces[m]
                if iface.channel_mode != "on":
                    continue
                peer = topo.neighbours(dev_id, m)
                peer_dev = topo.devices.get(peer[0]) if peer else None
                if peer_dev is None or peer_dev.model != DeviceModel.SWITCH:
                    continue                       # a host or router: no BPDUs, no loop
                peer_iface = peer_dev.interfaces.get(peer[1])
                if peer_iface is not None and peer_iface.channel_mode != "on":
                    bad.append(m)
            if not bad:
                continue
            members = " ".join(pc.bundled)
            sim.log_event(dev_id, "SPANTREE", 2, "CHNL_MISCFG",
                          f"Detected loop due to etherchannel misconfiguration of {pc.short} {members}")
            for m in list(pc.bundled):
                iface = topo.devices[dev_id].interfaces[m]
                if iface.err_disabled:
                    continue
                iface.err_disabled = "channel-misconfig"
                iface.err_disabled_at = sim.lab_time
                sim.log_event(dev_id, "PM", 4, "ERR_DISABLE",
                              f"channel-misconfig (STP) error detected on {pc.short}, "
                              f"putting {m} in err-disable state")
                tripped = True
    return tripped
