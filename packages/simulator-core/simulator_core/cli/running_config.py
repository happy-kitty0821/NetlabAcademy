"""
Building blocks of ``show running-config``.
"""

from __future__ import annotations

from ipaddress import IPv4Network

from simulator_core.types import InterfaceState
from simulator_core.cli.helpers import _cisco_mac, _long_name
from simulator_core.cli.switching import _ERRDISABLE_CAUSES
from simulator_core.cli.vlan import VlanCommands


def _switch_global_lines(switch) -> list[str]:
    """errdisable recovery and MAC address table lines of the running-config."""
    lines = []
    names = [n for n, _ in _ERRDISABLE_CAUSES]
    lines += [f"errdisable recovery cause {n}" for n in names if n in switch.errdisable_recovery]
    if switch.errdisable_interval != 300:
        lines.append(f"errdisable recovery interval {switch.errdisable_interval}")
    if switch.mac_aging_time != 300:
        lines.append(f"mac address-table aging-time {switch.mac_aging_time}")
    for (mac, vlan), port in sorted(switch.static_macs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        lines.append(f"mac address-table static {_cisco_mac(mac)} vlan {vlan} "
                     f"interface {_long_name(port)}")
    return lines


def _stp_global_lines(stp) -> list[str]:
    """Global spanning-tree lines of the running-config, in IOS order."""
    lines = [f"spanning-tree mode {stp.mode.value}", "spanning-tree extend system-id"]
    if getattr(stp, "_portfast_default", False):
        lines.append("spanning-tree portfast default")
    by_priority: dict[int, list[int]] = {}
    for vlan_id, priority in stp.configured_priorities().items():
        by_priority.setdefault(priority, []).append(vlan_id)
    # IOS prints one line per priority, VLANs as a range list, in VLAN order.
    for priority, vlans in sorted(by_priority.items(), key=lambda kv: kv[1][0]):
        lines.append(f"spanning-tree vlan {VlanCommands._format_vlan_list(vlans)} priority {priority}")
    return lines


def _stp_iface_lines(stp, name: str) -> list[str]:
    """Per-interface spanning-tree lines (only non-default settings)."""
    ports = [(inst.vlan_id, inst.port_states[name])
             for inst in sorted(stp.all_instances(), key=lambda i: i.vlan_id)
             if name in inst.port_states]
    if not ports:
        return []
    lines: list[str] = []
    first = ports[0][1]
    if first.portfast:
        lines.append(" spanning-tree portfast")
    if first.bpduguard:
        lines.append(" spanning-tree bpduguard enable")
    if first.bpdufilter:
        lines.append(" spanning-tree bpdufilter enable")
    if first.guard in ("root", "loop"):
        lines.append(f" spanning-tree guard {first.guard}")
    prios = {vid: (p.port_id.priority if p.port_id else 128) for vid, p in ports}
    costs = {vid: p.path_cost for vid, p in ports if p.cost_configured}
    # One value on every VLAN -> the short form; otherwise per-VLAN lines.
    if len(set(prios.values())) == 1:
        prio = next(iter(prios.values()))
        if prio != 128:
            lines.append(f" spanning-tree port-priority {prio}")
    else:
        lines += [f" spanning-tree vlan {v} port-priority {p}" for v, p in prios.items() if p != 128]
    if costs and len(costs) == len(ports) and len(set(costs.values())) == 1:
        lines.append(f" spanning-tree cost {next(iter(costs.values()))}")
    else:
        lines += [f" spanning-tree vlan {v} cost {c}" for v, c in costs.items()]
    return lines


def _port_security_lines(ps) -> list[str]:
    """Interface port-security lines (non-default settings), IOS order."""
    lines = []
    if ps.enabled:
        lines.append(" switchport port-security")
    if ps.maximum != 1:
        lines.append(f" switchport port-security maximum {ps.maximum}")
    if ps.violation != "shutdown":
        lines.append(f" switchport port-security violation {ps.violation}")
    if ps.aging_time:
        lines.append(f" switchport port-security aging time {ps.aging_time}")
    if ps.aging_type != "absolute":
        lines.append(f" switchport port-security aging type {ps.aging_type}")
    if ps.sticky:
        lines.append(" switchport port-security mac-address sticky")
    ordered = sorted(ps.addresses.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    lines += [f" switchport port-security mac-address sticky {_cisco_mac(mac)}"
              for (mac, _), a in ordered if a.kind == "SecureSticky"]
    lines += [f" switchport port-security mac-address {_cisco_mac(mac)}"
              for (mac, _), a in ordered if a.kind == "SecureConfigured"]
    return lines


def _iface_config_lines(device, name: str, iface, stp=None, psec=None) -> list[str]:
    """
    Running-configuration block for one interface, in IOS order.

    IOS prints only non-default settings: ``shutdown`` appears when the
    port is disabled (there is no ``no shutdown`` line), switchport lines
    appear only on switch ports, and an unaddressed routed interface shows
    ``no ip address``.
    """
    from ipaddress import IPv4Network
    from simulator_core.types import DeviceModel

    lines = [f"interface {_long_name(name)}"]
    desc = getattr(iface, "_description", "")
    if desc:
        lines.append(f" description {desc}")
    if iface.is_subinterface and iface.dot1q_vlan is not None:
        native = " native" if iface.dot1q_native else ""
        lines.append(f" encapsulation dot1Q {iface.dot1q_vlan}{native}")
    is_switchport = device.model == DeviceModel.SWITCH and iface.is_physical_switchport
    if iface.ip_config:
        mask = IPv4Network(f"0.0.0.0/{iface.ip_config.prefix_length}").netmask
        lines.append(f" ip address {iface.ip_config.address} {mask}")
    elif not is_switchport and device.model != DeviceModel.HOST:
        lines.append(" no ip address")
    if is_switchport:
        mode = iface.switchport_mode
        if iface.vlan != 1 and mode != "trunk":
            lines.append(f" switchport access vlan {iface.vlan}")
        if mode != "access":
            if iface.trunk_native_vlan != 1:
                lines.append(f" switchport trunk native vlan {iface.trunk_native_vlan}")
            if iface.trunk_allowed_vlans is not None:
                allowed = VlanCommands._format_vlan_list(sorted(iface.trunk_allowed_vlans))
                lines.append(f" switchport trunk allowed vlan {allowed}")
        if mode == "trunk":
            lines.append(" switchport mode trunk")
        elif mode.startswith("dynamic_"):
            lines.append(f" switchport mode dynamic {mode[len('dynamic_'):]}")
        elif mode == "access" and (iface.vlan != 1 or iface.dtp_nonegotiate
                                   or (psec is not None and psec.enabled)):
            lines.append(" switchport mode access")
        if iface.dtp_nonegotiate:
            lines.append(" switchport nonegotiate")
    if is_switchport and psec is not None:
        lines += _port_security_lines(psec)
    if is_switchport and stp is not None:
        lines += _stp_iface_lines(stp, name)
    if iface.admin_state == InterfaceState.DOWN:
        lines.append(" shutdown")
    lines.append("!")
    return lines
