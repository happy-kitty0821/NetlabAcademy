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

Management plane:
- A switch virtual interface (``interface vlan N`` with an IP address)
  answers ARP and ping in its VLAN, and the switch can ping from it,
  reaching other subnets through ``ip default-gateway``.

No host I/O, no sockets, no subprocess.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
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
from simulator_core.l2.stp import STPManager, STPMode, PortState
from simulator_core.topology import Device
from simulator_core.types import DEFAULT_VLAN, InterfaceState
from simulator_core.l2.cdp import CDPManager
from simulator_core.l2.etherchannel import (  # noqa: F401  (re-exported)
    DEFAULT_LOAD_BALANCE, EtherChannelMode, EtherChannelProtocol, PortChannelGroup,
    copy_l2_config, l2_config, protocols_compatible,
)
from simulator_core.l2.port_security import (
    SECURE_CONFIGURED, SECURE_DYNAMIC, SECURE_STICKY, PortSecurity, SecureAddress,
)

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


# ---------------------------------------------------------------------------
# Switch
# ---------------------------------------------------------------------------

# A frame reaching the same switch more often than this is circling a loop.
LOOP_FRAME_LIMIT = 3

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

        # MAC table extras: when each dynamic entry was last seen (lab
        # seconds), static entries, and the aging time (0 = never age).
        self._mac_seen: dict[tuple[str, int], float] = {}
        self._static_macs: dict[tuple[str, int], str] = {}
        self.mac_aging_time: int = 300

        # errdisable recovery: causes that recover automatically, and after
        # how many seconds ("errdisable recovery cause/interval").
        self.errdisable_recovery: set[str] = set()
        self.errdisable_interval: int = 300

        # switchport port-security, per port (created on first use).
        self._psec: dict[str, PortSecurity] = {}

        # Loop safety: how often each frame has reached this switch (a frame
        # that keeps coming back is circling a switching loop) and how often
        # each address moved between ports (MAC flapping).
        self._frames_seen: dict[tuple, int] = {}
        self._mac_moves: dict[tuple[str, int], int] = {}
        self._flap_logged: set[tuple[str, int]] = set()

        # EtherChannel groups: group_id → PortChannelGroup
        self._port_channels: dict[int, PortChannelGroup] = {}
        # port-channel load-balance <method>
        self.load_balance: str = DEFAULT_LOAD_BALANCE

        # Reverse mapping: member iface → group_id
        self._member_to_pc: dict[str, int] = {}

        # STP manager
        self._stp = STPManager(
            device_id=device.id,
            mac=list(device.interfaces.values())[0].mac.value
                if device.interfaces else "00:00:00:00:00:01",
        )
        # Factory STP mode of this switch model (before any instance exists)
        if device.stp_mode:
            self._stp.mode = STPMode(device.stp_mode)
        # Initialise STP for VLAN 1
        self._stp.ensure_vlan(1)

        # Register all physical interfaces with STP instances.
        self._register_stp_ports()
        # Re-run the network-wide election whenever STP settings change.
        if simulation is not None:
            self._stp.on_change = simulation._trigger_stp
        # PVST+: each VLAN's tree runs only over ports carrying that VLAN.
        self._stp.port_vlan_filter = self._stp_port_in_vlan

        # CDP manager
        hostname = device.hostname if hasattr(device, "hostname") else device.id
        self.cdp_manager = CDPManager(
            device_id=device.id,
            hostname=hostname,
            capabilities="Switch",
            platform="Cisco Catalyst 2960",
        )

        # Management plane (SVI) state.
        self._mgmt_arp: dict = {}            # IPv4Address -> MACAddress
        self._mgmt_pending_arp: dict = {}    # next hop -> [(seq, result, dst, src, vlan)]
        self._mgmt_pending_echo: dict = {}   # (seq, ident) -> (send_tick, result)

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
            from simulator_core.l2.stp import PortID
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
        from simulator_core.l2.stp import PortID
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
        # IOS keeps "switchport access vlan N" on the member ports: they go
        # inactive (carry no traffic) until VLAN N is created again.
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

    def clear_dynamic_mac_addresses(self, address: Optional[str] = None,
                                    interface: Optional[str] = None,
                                    vlan: Optional[int] = None) -> int:
        """
        clear mac address-table dynamic [address M | interface I | vlan N]
        — returns how many entries were removed.
        """
        doomed = [k for k, port in self._mac_table.items()
                  if (address is None or k[0] == address)
                  and (interface is None or port == interface)
                  and (vlan is None or k[1] == vlan)]
        for k in doomed:
            self._mac_table.pop(k, None)
            self._mac_seen.pop(k, None)
        return len(doomed)

    # ------------------------------------------------------------------
    # MAC table: static entries, aging, listing
    # ------------------------------------------------------------------

    @property
    def static_macs(self) -> dict[tuple[str, int], str]:
        return dict(self._static_macs)

    def add_static_mac(self, mac: str, vlan: int, port: str) -> None:
        key = (mac, vlan)
        self._static_macs[key] = port
        # A static entry replaces any dynamic one for the same address.
        self._mac_table.pop(key, None)
        self._mac_seen.pop(key, None)

    def remove_static_mac(self, mac: str, vlan: int, port: Optional[str] = None) -> bool:
        key = (mac, vlan)
        if key not in self._static_macs or (port is not None and self._static_macs[key] != port):
            return False
        del self._static_macs[key]
        return True

    def mac_lookup(self, mac: str, vlan: int) -> Optional[str]:
        """
        Port for *mac* in *vlan*: static entries first, then secure
        addresses (port security), then learned ones.
        """
        key = (mac, vlan)
        return (self._static_macs.get(key) or self._secure_owner(key)
                or self._mac_table.get(key))

    def mac_entries(self) -> list[tuple[int, str, str, str]]:
        """
        (vlan, mac, "STATIC"|"DYNAMIC", port) for every entry.  Secure
        addresses are listed as STATIC, as IOS does.
        """
        rows = [(v, m, "STATIC", p) for (m, v), p in self._static_macs.items()]
        seen = set(self._static_macs)
        for port, ps in self._psec.items():
            if ps.enabled:
                for key in ps.addresses:
                    if key not in seen:
                        rows.append((key[1], key[0], "STATIC", port))
                        seen.add(key)
        rows += [(v, m, "DYNAMIC", p) for (m, v), p in self._mac_table.items()
                 if (m, v) not in seen]
        return rows

    # ------------------------------------------------------------------
    # Port security
    # ------------------------------------------------------------------

    def port_security(self, port: str) -> PortSecurity:
        """The port's security settings (created with IOS defaults)."""
        return self._psec.setdefault(port, PortSecurity())

    def port_security_config(self, port: str) -> Optional[PortSecurity]:
        """The port's settings, or None if port security was never touched."""
        return self._psec.get(port)

    def secure_ports(self) -> dict[str, PortSecurity]:
        return {p: ps for p, ps in self._psec.items() if ps.enabled}

    def _secure_owner(self, key: tuple[str, int]) -> Optional[str]:
        for port, ps in self._psec.items():
            if ps.enabled and key in ps.addresses:
                return port
        return None

    def secure_address_owner(self, mac: str, vlan: int, exclude: Optional[str] = None) -> Optional[str]:
        """Secure port (other than *exclude*) holding *mac* in *vlan*."""
        for port, ps in self._psec.items():
            if port != exclude and (mac, vlan) in ps.addresses:
                return port
        return None

    def _psec_vlan(self, port: str) -> int:
        iface = self._device.interfaces.get(port)
        if iface is None:
            return DEFAULT_VLAN
        return iface.trunk_native_vlan if iface.is_trunk else iface.vlan

    def check_port_security(self, port: str, mac: str, vlan: int) -> bool:
        """
        Apply port security to a frame from *mac* received on *port*.
        Returns False when the frame must be dropped (a violation).
        """
        ps = self._psec.get(port)
        if ps is None or not ps.enabled:
            return True
        now = self._sim.lab_time
        key = (mac, vlan)
        ps.last_source = key
        known = ps.addresses.get(key)
        if known is not None:
            known.last_seen = now
            return True
        # An address secured on another port arriving here is a violation
        # (a "MAC move" between secure ports).
        if self.secure_address_owner(mac, vlan, exclude=port) is None \
                and len(ps.addresses) < ps.maximum:
            kind = SECURE_STICKY if ps.sticky else SECURE_DYNAMIC
            ps.addresses[key] = SecureAddress(kind=kind, learned_at=now, last_seen=now)
            self._mac_table.pop(key, None)
            self._mac_seen.pop(key, None)
            return True
        self._psec_violation(port, ps, mac, vlan)
        return False

    def _psec_violation(self, port: str, ps: PortSecurity, mac: str, vlan: int) -> None:
        if ps.violation == "protect":
            return                      # dropped silently, not counted
        ps.violation_count += 1
        from simulator_core.naming import long_name
        digits = mac.replace(":", "")
        cisco = f"{digits[0:4]}.{digits[4:8]}.{digits[8:12]}"
        message = (f"Security violation occurred, caused by MAC address {cisco} "
                   f"on port {long_name(port)}.")
        if ps.violation == "shutdown":
            iface = self._device.interfaces.get(port)
            if iface is not None and iface.err_disabled:
                return
            self._sim.err_disable(self.device_id, port, "psecure-violation")
            self._sim.log_event(self.device_id, "PORT_SECURITY", 2, "PSECURE_VIOLATION", message)
            self._sim.refresh_interface_states()
        else:                           # restrict
            self._sim.log_event(self.device_id, "PORT_SECURITY", 2, "PSECURE_VIOLATION", message)

    def age_port_security(self, now: float) -> None:
        for ps in self._psec.values():
            for key in ps.expired(now):
                del ps.addresses[key]

    def clear_port_security(self, kinds: set[str], port: Optional[str] = None,
                            mac: Optional[str] = None) -> int:
        """clear port-security ... — remove secure addresses of *kinds*."""
        removed = 0
        for name, ps in self._psec.items():
            if port is not None and name != port:
                continue
            for key in [k for k, a in ps.addresses.items()
                        if a.kind in kinds and (mac is None or k[0] == mac)]:
                del ps.addresses[key]
                removed += 1
        return removed

    def age_mac_table(self, now: float) -> int:
        """Drop dynamic entries not seen for the aging time; returns how many."""
        if self.mac_aging_time <= 0:
            return 0
        expired = [k for k, seen in self._mac_seen.items() if now - seen >= self.mac_aging_time]
        for k in expired:
            self._mac_seen.pop(k, None)
            self._mac_table.pop(k, None)
        return len(expired)

    def flush_port_macs(self, port: str) -> None:
        """A port going down forgets the addresses it learned (IOS)."""
        for k in [k for k, p in self._mac_table.items() if p == port]:
            self._mac_table.pop(k, None)
            self._mac_seen.pop(k, None)
        # Secure dynamic addresses go with the link; sticky and configured
        # ones stay.
        ps = self._psec.get(port)
        if ps is not None:
            ps.remove_kind(SECURE_DYNAMIC)

    def bpdu_guard_enabled(self, port: str) -> bool:
        """BPDU guard is on for *port* (interface setting or portfast default)."""
        inst = self._stp.get_instance(1)
        ps = inst.port_states.get(port) if inst is not None else None
        return bool(ps is not None
                    and self._stp.bpduguard_enabled(ps, self._device.interfaces.get(port)))

    def sends_bpdus(self, port: str) -> bool:
        """Does this switch send BPDUs out of *port* (STP on, no BPDU filter)?"""
        if not self._stp.enabled:
            return False
        inst = self._stp.get_instance(1)
        ps = inst.port_states.get(port) if inst is not None else None
        return not (ps is not None and ps.bpdufilter)

    def ports_in_vlan(self, vlan_id: int) -> list[str]:
        result = []
        for name, iface in self._device.interfaces.items():
            if iface.is_access and iface.vlan == vlan_id:
                result.append(name)
            elif iface.is_trunk:
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
        if iface is None or not iface.is_trunk:
            return []
        allowed = iface.trunk_allowed_vlans
        if allowed is None:
            return sorted(self._vlans.keys())
        return sorted(v for v in allowed if v in self._vlans)

    # ------------------------------------------------------------------
    # EtherChannel management
    # ------------------------------------------------------------------

    def ensure_port_channel(self, group_id: int, template=None) -> tuple[PortChannelGroup, bool]:
        """
        The port-channel *group_id*, created (with its ``PoN`` interface)
        if needed.  A new ``PoN`` copies the layer 2 settings of *template*
        (the first member).  Returns (group, interface_was_created).
        """
        pc = self._port_channels.get(group_id)
        if pc is None:
            pc = PortChannelGroup(group_id)
            pc.created_at = self._sim.lab_time if self._sim is not None else 0.0
            self._port_channels[group_id] = pc
        if pc.short in self._device.interfaces:
            return pc, False
        from simulator_core.l2.etherchannel import port_channel_mac
        from simulator_core.topology import Interface
        po = Interface(name=pc.short, mac=port_channel_mac(self.device_id, pc.short))
        if template is not None:
            copy_l2_config(template, po)
        self._device.add_interface(po)
        pc.synced = l2_config(po)
        self.register_interface_with_stp(pc.short)
        return pc, True

    def add_port_channel(self, group_id: int, iface_name: str,
                         protocol: str = "on") -> PortChannelGroup:
        """
        channel-group <id> mode <protocol> on *iface_name*.  A port joining
        an existing port-channel takes on its configuration (IOS); the first
        port of a new one gives it its own.
        """
        iface = self._device.interfaces[iface_name]
        old = self._member_to_pc.get(iface_name)
        if old is not None and old != group_id:
            self.remove_port_channel_member(iface_name)
        pc, created = self.ensure_port_channel(group_id, template=iface)
        if not created:
            copy_l2_config(self._device.interfaces[pc.short], iface)
        pc.protocol = protocol
        pc.add_member(iface_name)
        self._member_to_pc[iface_name] = group_id
        iface.channel_group = group_id
        iface.channel_mode = protocol
        return pc

    def remove_port_channel_member(self, iface_name: str) -> None:
        """no channel-group: the port leaves its port-channel (which stays)."""
        gid = self._member_to_pc.pop(iface_name, None)
        if gid is not None and gid in self._port_channels:
            self._port_channels[gid].remove_member(iface_name)
        iface = self._device.interfaces.get(iface_name)
        if iface is not None:
            iface.channel_group = iface.channel_mode = iface.ec_state = None

    def remove_port_channel(self, group_id: int) -> bool:
        """no interface port-channel N: delete the bundle and its interface."""
        pc = self._port_channels.pop(group_id, None)
        if pc is None:
            return False
        for m in list(pc.members):
            self._member_to_pc.pop(m, None)
            iface = self._device.interfaces.get(m)
            if iface is not None:
                iface.channel_group = iface.channel_mode = iface.ec_state = None
        self._device.interfaces.pop(pc.short, None)
        self._stp.unregister_port(pc.short)
        self.flush_port_macs(pc.short)
        return True

    def get_port_channel_for(self, iface_name: str) -> Optional[PortChannelGroup]:
        gid = self._member_to_pc.get(iface_name)
        return self._port_channels.get(gid) if gid is not None else None

    def _get_logical_egress(self, iface_name: str, src_mac: str, dst_mac: str,
                            frame: Optional[EthernetFrame] = None) -> list[str]:
        """
        The physical port(s) a frame sent out of *iface_name* uses: for a
        port-channel, one bundled member picked by the load-balance hash.
        """
        if iface_name.lower().startswith("po"):
            for pc in self._port_channels.values():
                if pc.short == iface_name:
                    packet = frame.payload if frame is not None else None
                    src_ip = str(getattr(packet, "src", "")) or None
                    dst_ip = str(getattr(packet, "dst", "")) or None
                    selected = pc.select_egress(src_mac, dst_mac, self.load_balance,
                                                src_ip, dst_ip)
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
        from simulator_core.l2.stp import PortRole, PortState, BridgeID
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

        # --- BPDUGuard: err-disable the port on BPDU receipt ---
        if port_state.bpduguard:
            port_state.state = PortState.ERR_DISABLED
            port_state.role  = PortRole.DISABLED
            if self._sim is not None:
                self._sim.bpdu_guard_trip(self.device_id, ingress_iface)
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

        # EtherChannel: a bundled member's frames arrive on its port-channel;
        # a suspended or down member carries nothing.
        if iface.channel_group is not None and iface.ec_state != "I":
            if iface.ec_state != "P":
                self._sim._record(FrameDropped(
                    time=arrive_time, seq=self._sim.next_seq(),
                    device_id=self.device_id,
                    interface_name=ingress_iface,
                    frame=frame,
                    reason="EtherChannel member not bundled",
                ))
                return
            ingress_iface = f"Po{iface.channel_group}"
            iface = self._device.interfaces[ingress_iface]

        # Classify the frame into a VLAN (802.1Q ingress rules).
        if iface.is_trunk:
            # Tagged frames belong to the VLAN in their tag; untagged frames
            # belong to the trunk's native VLAN.  A VLAN not allowed on this
            # trunk is dropped at ingress.
            if frame.vlan_tag is not None:
                vlan = frame.vlan_tag
            else:
                vlan = iface.trunk_native_vlan
            if not self._is_vlan_allowed_on_trunk(ingress_iface, vlan):
                self._sim._record(FrameDropped(
                    time=arrive_time, seq=self._sim.next_seq(),
                    device_id=self.device_id,
                    interface_name=ingress_iface,
                    frame=frame,
                    reason=f"VLAN {vlan} not allowed on trunk",
                ))
                return
        else:
            # Access ports carry untagged frames only.
            if frame.vlan_tag is not None:
                self._sim._record(FrameDropped(
                    time=arrive_time, seq=self._sim.next_seq(),
                    device_id=self.device_id,
                    interface_name=ingress_iface,
                    frame=frame,
                    reason="802.1Q-tagged frame received on access port",
                ))
                return
            vlan = iface.vlan

        # A VLAN missing from the VLAN database is inactive: an access port
        # left in a deleted VLAN, or a tagged VLAN this switch does not have.
        if vlan not in self._vlans:
            self._sim._record(FrameDropped(
                time=arrive_time, seq=self._sim.next_seq(),
                device_id=self.device_id,
                interface_name=ingress_iface,
                frame=frame,
                reason=f"VLAN {vlan} is not in the VLAN database (inactive)",
            ))
            return

        # Switching loop: the same frame keeps arriving.  A real network
        # melts down (broadcast storm); the simulator drops the copies so the
        # lab stays responsive, and the MAC flapping it causes is logged.
        loop_key = (frame.frame_id, frame.src_mac.value, vlan)
        if len(self._frames_seen) > 20_000:
            self._frames_seen.clear()
        seen = self._frames_seen.get(loop_key, 0) + 1
        self._frames_seen[loop_key] = seen
        if seen > LOOP_FRAME_LIMIT:
            self._sim._record(FrameDropped(
                time=arrive_time, seq=self._sim.next_seq(),
                device_id=self.device_id,
                interface_name=ingress_iface,
                frame=frame,
                reason="switching loop: frame seen repeatedly",
            ))
            return

        # Port security: an unknown or misplaced source address on a secure
        # port is a violation.
        if not self.check_port_security(ingress_iface, frame.src_mac.value, vlan):
            self._sim._record(FrameDropped(
                time=arrive_time, seq=self._sim.next_seq(),
                device_id=self.device_id,
                interface_name=ingress_iface,
                frame=frame,
                reason="port-security violation",
            ))
            return

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
        # The switch's own management interface in this VLAN sees the frame
        # first.  Frames addressed to the SVI stop here; broadcasts are
        # processed and still flooded.
        if self._svi_receive(arrive_time, frame, vlan):
            return

        dst_mac = frame.dst_mac.value
        if frame.dst_mac.is_broadcast:
            self._flood_in_vlan(arrive_time, frame, ingress_iface, vlan)
        else:
            known_port = self.mac_lookup(dst_mac, vlan)
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

    def _stp_port_in_vlan(self, iface_name: str, vlan_id: int) -> bool:
        """
        A port takes part in VLAN *vlan_id*'s spanning tree when the VLAN
        exists in the VLAN database and the port carries it (its access
        VLAN, or allowed on its trunk).
        """
        return vlan_id in self._vlans and self._port_carries_vlan(iface_name, vlan_id)

    def _port_carries_vlan(self, iface_name: str, vlan_id: int) -> bool:
        """True if this port should carry traffic for vlan_id."""
        iface = self._device.interfaces.get(iface_name)
        if iface is None or not iface.is_physical_switchport:
            return False
        if vlan_id not in self._vlans:
            return False      # deleted / never created: inactive
        if iface.is_access:
            return iface.vlan == vlan_id
        elif iface.is_trunk:
            return self._is_vlan_allowed_on_trunk(iface_name, vlan_id)
        return False

    # ------------------------------------------------------------------
    # Forwarding internals
    # ------------------------------------------------------------------

    def _learn(self, time: int, mac_value: str,
               iface_name: str, vlan: int) -> None:
        key = (mac_value, vlan)
        if key in self._static_macs:
            return            # a static entry is never overwritten
        ps = self._psec.get(iface_name)
        if ps is not None and ps.enabled:
            return            # secure ports keep their addresses in port security
        self._mac_seen[key] = self._sim.lab_time
        old_port = self._mac_table.get(key)
        if old_port is not None and old_port != iface_name:
            moves = self._mac_moves.get(key, 0) + 1
            self._mac_moves[key] = moves
            if moves >= 2 and key not in self._flap_logged:
                self._flap_logged.add(key)
                digits = mac_value.replace(":", "")
                self._sim.log_event(
                    self.device_id, "SW_MATM", 4, "MACFLAP_NOTIF",
                    f"Host {digits[0:4]}.{digits[4:8]}.{digits[8:12]} in vlan {vlan} is flapping "
                    f"between port {old_port} and port {iface_name}")
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
                elif iface.is_access:
                    stp_vlan = iface.vlan
                else:
                    stp_vlan = iface.trunk_native_vlan
                if not self._stp.is_port_forwarding(egress_iface, stp_vlan):
                    return  # Drop — egress port is STP discarding/blocking
        # Resolve EtherChannel if needed
        physical_ports = self._get_logical_egress(egress_iface, src_mac, dst_mac, frame)
        for port in physical_ports:
            self._send_on_port(time, self._encapsulate_for_egress(frame, port, frame_vlan), port)

    def _encapsulate_for_egress(self, frame: EthernetFrame, egress_iface: str,
                                frame_vlan: Optional[int]) -> EthernetFrame:
        """
        Apply 802.1Q egress rules: a trunk port tags every VLAN except its
        native VLAN; an access port always sends untagged.  BPDU and CDP
        frames are left as the control plane built them.
        """
        if frame.bpdu_payload is not None or frame.cdp_payload is not None:
            return frame
        iface = self._device.interfaces.get(egress_iface)
        tag: Optional[int] = None
        if (iface is not None and iface.is_trunk
                and frame_vlan is not None
                and frame_vlan != iface.trunk_native_vlan):
            tag = frame_vlan
        if frame.vlan_tag == tag:
            return frame
        return replace(frame, vlan_tag=tag)

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
        for iface_name, port in self._device.interfaces.items():
            if iface_name == ingress_iface:
                continue
            if port.in_bundle:
                continue        # reached through its port-channel
            if not self._port_carries_vlan(iface_name, vlan):
                continue
            if not self._stp.is_port_forwarding(iface_name, vlan):
                continue
            self._forward(time, frame, iface_name,
                          frame.src_mac.value, frame.dst_mac.value,
                          frame_vlan=vlan)

    # ------------------------------------------------------------------
    # Management plane: SVI ARP / ICMP and switch-originated ping
    # ------------------------------------------------------------------

    _MGMT_ICMP_IDENTIFIER = 0x5157
    _MGMT_RTT_SPACING = 6

    def _active_svi(self, vlan: int):
        """The SVI for *vlan* if it has an address and is up/up, else None."""
        svi = self._device.interfaces.get(f"Vlan{vlan}")
        if (svi is None or svi.ip_config is None
                or svi.admin_state != InterfaceState.UP
                or svi.oper_state != InterfaceState.UP):
            return None
        return svi

    def _svi_receive(self, time: int, frame: EthernetFrame, vlan: int) -> bool:
        """
        Let the VLAN's SVI process *frame*.  Returns True when the frame was
        addressed to the SVI and must not be forwarded further.
        """
        from simulator_core.frames import ARPMessage, ICMPMessage, IPv4Packet

        svi = self._active_svi(vlan)
        if svi is None:
            return False
        own_ip = svi.ip_config.address

        if frame.ethertype == EthernetFrame.ETHERTYPE_ARP and isinstance(frame.payload, ARPMessage):
            arp = frame.payload
            if arp.target_ip == own_ip or arp.sender_ip in self._mgmt_pending_arp:
                self._mgmt_arp[arp.sender_ip] = arp.sender_mac
            if arp.operation == ARPMessage.ARP_REQUEST and arp.target_ip == own_ip:
                reply = ARPMessage(
                    operation=ARPMessage.ARP_REPLY,
                    sender_mac=svi.mac, sender_ip=own_ip,
                    target_mac=arp.sender_mac, target_ip=arp.sender_ip,
                )
                self._svi_send(time + 1, EthernetFrame(
                    src_mac=svi.mac, dst_mac=arp.sender_mac,
                    ethertype=EthernetFrame.ETHERTYPE_ARP, payload=reply,
                    frame_id=self._frame_id(),
                ), vlan)
            elif arp.operation == ARPMessage.ARP_REPLY and frame.dst_mac == svi.mac:
                self._mgmt_unblock(arp.sender_ip, arp.sender_mac)
            return frame.dst_mac == svi.mac

        if frame.dst_mac != svi.mac:
            return False
        if (frame.ethertype == EthernetFrame.ETHERTYPE_IPV4
                and isinstance(frame.payload, IPv4Packet)
                and frame.payload.dst == own_ip
                and frame.payload.protocol == IPv4Packet.PROTOCOL_ICMP):
            pkt = frame.payload
            icmp = pkt.payload
            if icmp.type == ICMPMessage.ECHO_REQUEST:
                reply = IPv4Packet(
                    src=own_ip, dst=pkt.src, protocol=IPv4Packet.PROTOCOL_ICMP,
                    ttl=255,
                    payload=ICMPMessage(
                        type=ICMPMessage.ECHO_REPLY, code=0,
                        sequence=icmp.sequence, identifier=icmp.identifier,
                    ),
                )
                self._svi_send(time + 1, EthernetFrame(
                    src_mac=svi.mac, dst_mac=frame.src_mac,
                    ethertype=EthernetFrame.ETHERTYPE_IPV4, payload=reply,
                    frame_id=self._frame_id(),
                ), vlan)
            elif icmp.type == ICMPMessage.ECHO_REPLY:
                self._mgmt_complete_echo(time, icmp)
        return True

    def _svi_send(self, t: int, frame: EthernetFrame, vlan: int) -> None:
        """Inject a frame originated by the SVI into the VLAN at tick *t*."""
        svi_name = f"Vlan{vlan}"
        known = None if frame.dst_mac.is_broadcast else self.mac_lookup(
            frame.dst_mac.value, vlan)
        # _forward/_flood transmit at (time + 1), so pass t - 1.
        if known is not None and self._port_carries_vlan(known, vlan):
            self._forward(t - 1, frame, known, frame.src_mac.value,
                          frame.dst_mac.value, frame_vlan=vlan)
        else:
            self._flood_in_vlan(t - 1, frame, svi_name, vlan)

    @staticmethod
    def _frame_id() -> str:
        import uuid
        return str(uuid.uuid4())

    def ping(self, dst_ip: str, count: int = 5):
        """
        Ping from the switch's management SVI (IOS ``ping`` on a 2960).

        The source SVI is the one whose subnet contains the destination;
        otherwise traffic goes to ``ip default-gateway`` through the SVI on
        the gateway's subnet.  As on IOS, the first echo is lost while ARP
        resolves the next hop.
        """
        from ipaddress import IPv4Address
        from simulator_core.devices.host import EchoResult, PingResult
        from simulator_core.devices.router import DROP_ARP_PENDING

        dst = IPv4Address(dst_ip)
        result = PingResult(target_ip=dst_ip, count=count, sent=count, received=0)
        self._mgmt_pending_arp.clear()
        self._mgmt_pending_echo.clear()

        def fail_all(reason: str):
            for seq in range(count):
                result.results.append(EchoResult(
                    sequence=seq, success=False, rtt_ticks=None, drop_reason=reason,
                ))
            return result

        svis = []
        for name, iface in self._device.interfaces.items():
            if iface.is_svi:
                try:
                    vlan = int(name[4:])
                except ValueError:
                    continue
                if self._active_svi(vlan) is not None:
                    svis.append((vlan, iface))
        if not svis:
            return fail_all(
                "no management interface is up - configure 'interface vlan N' "
                "with an IP address and 'no shutdown'"
            )

        for vlan, svi in svis:
            if svi.ip_config.address == dst:
                for seq in range(count):
                    result.results.append(EchoResult(
                        sequence=seq, success=True, rtt_ticks=0, drop_reason=None,
                    ))
                result.received = count
                return result

        chosen = next(((v, i) for v, i in svis if dst in i.ip_config.network), None)
        next_hop = dst
        if chosen is None:
            gw_str = getattr(self._device.config, "ip_default_gateway", "") or ""
            if not gw_str:
                return fail_all("destination is not on a management subnet and no "
                                "'ip default-gateway' is configured")
            next_hop = IPv4Address(gw_str)
            chosen = next(((v, i) for v, i in svis if next_hop in i.ip_config.network), None)
            if chosen is None:
                return fail_all("the default gateway is not on any management subnet")
        vlan, svi = chosen
        src = svi.ip_config.address

        if next_hop in self._mgmt_arp:
            mac = self._mgmt_arp[next_hop]
            for seq in range(count):
                self._mgmt_send_echo(dst, src, mac, vlan, seq, result,
                                     self._sim.clock + 1 + seq * self._MGMT_RTT_SPACING)
            return result

        result.results.append(EchoResult(
            sequence=0, success=False, rtt_ticks=None, drop_reason=DROP_ARP_PENDING,
        ))
        self._mgmt_pending_arp[next_hop] = [
            (seq, result, dst, src, vlan) for seq in range(1, count)
        ]
        from simulator_core.addresses import BROADCAST_MAC, ZERO_MAC
        from simulator_core.frames import ARPMessage
        request = ARPMessage(
            operation=ARPMessage.ARP_REQUEST,
            sender_mac=svi.mac, sender_ip=src,
            target_mac=ZERO_MAC, target_ip=next_hop,
        )
        self._svi_send(self._sim.clock + 1, EthernetFrame(
            src_mac=svi.mac, dst_mac=BROADCAST_MAC,
            ethertype=EthernetFrame.ETHERTYPE_ARP, payload=request,
            frame_id=self._frame_id(),
        ), vlan)
        return result

    def _mgmt_unblock(self, ip, mac) -> None:
        pending = self._mgmt_pending_arp.pop(ip, [])
        for k, (seq, result, dst, src, vlan) in enumerate(pending):
            self._mgmt_send_echo(dst, src, mac, vlan, seq, result,
                                 self._sim.clock + 1 + k * self._MGMT_RTT_SPACING)

    def _mgmt_send_echo(self, dst, src, dst_mac, vlan, seq, result, t) -> None:
        from simulator_core.frames import ICMPMessage, IPv4Packet
        svi = self._device.interfaces[f"Vlan{vlan}"]
        pkt = IPv4Packet(
            src=src, dst=dst, protocol=IPv4Packet.PROTOCOL_ICMP, ttl=255,
            payload=ICMPMessage(
                type=ICMPMessage.ECHO_REQUEST, code=0,
                sequence=seq, identifier=self._MGMT_ICMP_IDENTIFIER,
            ),
        )
        self._svi_send(t, EthernetFrame(
            src_mac=svi.mac, dst_mac=dst_mac,
            ethertype=EthernetFrame.ETHERTYPE_IPV4, payload=pkt,
            frame_id=self._frame_id(),
        ), vlan)
        self._mgmt_pending_echo[(seq, self._MGMT_ICMP_IDENTIFIER)] = (t, result)

    def _mgmt_complete_echo(self, time: int, icmp) -> None:
        from simulator_core.devices.host import EchoResult
        entry = self._mgmt_pending_echo.pop((icmp.sequence, icmp.identifier), None)
        if entry is None:
            return
        send_tick, result = entry
        result.received += 1
        result.results.append(EchoResult(
            sequence=icmp.sequence, success=True,
            rtt_ticks=time - send_tick, drop_reason=None,
        ))

    @property
    def mgmt_arp_cache(self) -> dict:
        return dict(self._mgmt_arp)
