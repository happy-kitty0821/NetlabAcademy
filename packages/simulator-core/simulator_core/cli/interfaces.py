"""
Interface commands: entering interfaces, IP addressing,
shutdown, speed / duplex and the ``show interfaces`` family.
"""

from __future__ import annotations

import re
from ipaddress import IPv4Address, IPv4Network
from typing import Optional

from simulator_core.topology import Interface
from simulator_core.types import InterfaceState
from simulator_core.cli.engine import CLIMode, _invalid, _invalid_at
from simulator_core.cli.helpers import (
    _cisco_mac,
    _display_order,
    _expand_iface_range,
    _hardware_name,
    _is_valid_host_address,
    _join_iface_tokens,
    _long_name,
    _mask_prefix,
    _match_iface,
    _media_type,
    _speed_to_stp_cost,
    _split_iface_name,
    _status_words,
    _switch_port_status,
    _virtual_iface_mac,
)


class InterfaceCommands:
    """Interface commands: entering interfaces, IP addressing, (mixed into ``CLISession``)."""

    def _cmd_enter_iface(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        # Compact virtual-interface forms: "vlan1" → "vlan 1", "lo0" → "lo 0"
        compact = re.match(r"^([A-Za-z]+)(\d+)$", tokens[1])
        if compact and (
            "vlan".startswith(compact.group(1).lower())
            or "loopback".startswith(compact.group(1).lower())
        ):
            tokens = [tokens[0], compact.group(1), compact.group(2)] + tokens[2:]
        sub = tokens[1].lower()

        # Dispatch sub-types handled inline so the tree stays simple
        if sub == "range":
            return self._cmd_enter_iface_range(tokens)
        if "vlan".startswith(sub):
            return self._cmd_enter_svi(tokens)
        if "loopback".startswith(sub):
            return self._cmd_enter_loopback(tokens)
        pc = re.match(r"^([a-z-]+?)(\d*)$", sub)
        if pc and len(pc.group(1)) >= 2 and "port-channel".startswith(pc.group(1)):
            number = pc.group(2) or (tokens[2] if len(tokens) > 2 else "")
            return self._enter_port_channel(number)

        tokens = _join_iface_tokens(tokens, 1)
        iface_name = tokens[1]
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        iface_names = list(device.interfaces.keys())

        # Match with Cisco abbreviation support (type-aware, exact number)
        matches = _match_iface(iface_name, iface_names)
        if not matches:
            parsed = _split_iface_name(iface_name)
            if parsed and "." in parsed[1]:
                return self._cmd_enter_subinterface(iface_name, device)
            return f"% Invalid interface name: {iface_name!r}"
        if len(matches) > 1:
            return (
                f"% Ambiguous interface: {iface_name!r}\n"
                f"  Matches: {', '.join(matches)}"
            )
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = matches[0]
        self.current_range = []
        return ""

    def _cmd_enter_subinterface(self, typed: str, device) -> str:
        """
        ``interface g0/0.10`` on a router: create (or enter) a subinterface
        of the physical port.  Subinterfaces share the parent's MAC, as on
        IOS.  Switches have no routed subinterfaces.
        """
        from simulator_core.types import DeviceModel
        parent_typed, _, sub = typed.rpartition(".")
        if device.model != DeviceModel.ROUTER:
            return f"% Invalid interface name: {typed!r}"
        try:
            sub_id = int(sub)
        except ValueError:
            return f"% Invalid interface name: {typed!r}"
        if not 1 <= sub_id <= 4294967295:
            return f"% Invalid interface name: {typed!r}"
        physical = [n for n, i in device.interfaces.items()
                    if not (i.is_svi or i.is_loopback or i.is_subinterface)]
        parents = _match_iface(parent_typed, physical)
        if len(parents) != 1:
            return f"% Invalid interface name: {typed!r}"
        parent = device.interfaces[parents[0]]
        name = f"{parent.name}.{sub_id}"
        if name not in device.interfaces:
            device.add_interface(Interface(name=name, mac=parent.mac))
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = name
        self.current_range = []
        return ""

    def _cmd_enter_iface_range(self, tokens: list[str]) -> str:
        # tokens: ['interface', 'range', <spec...>]
        # e.g. "fa0/1 - 5", "fa0/1-5", "f0/1 - 2 , f0/5"
        if len(tokens) < 3:
            return "% Incomplete command.\nUsage: interface range <iface1> - <last-port>"
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        spec = " ".join(tokens[2:])
        members, err = _expand_iface_range(spec, list(device.interfaces.keys()))
        if err:
            return err
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = members[0]
        self.current_range = members
        return ""

    def _cmd_enter_svi(self, tokens: list[str]) -> str:
        # tokens: ['interface', 'vlan', '<vlan-id>']
        if len(tokens) < 3:
            return "% Incomplete command."
        try:
            vlan_id = int(tokens[2])
        except ValueError:
            return f"% Invalid VLAN ID: {tokens[2]!r}"
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."

        # Capability check — L2-only switches do not support SVIs.
        if not device.supports_svi:
            return (
                _invalid_at("interface vlan", "vlan")
                + "\n% SVI (interface vlan) is not supported on this device."
                "\n  Use 'ip default-gateway' for management access on a L2 switch."
            )

        if not 1 <= vlan_id <= 4094:
            return "% Invalid input: VLAN ID must be 1-4094."
        iface_name = f"Vlan{vlan_id}"
        if iface_name not in device.interfaces:
            # Create the SVI interface.  Vlan1 ships "shutdown" on IOS
            # switches, so it needs an explicit "no shutdown".
            iface = Interface(
                name=iface_name,
                mac=_virtual_iface_mac(self.device_id, iface_name),
            )
            if vlan_id == 1:
                iface.admin_state = InterfaceState.DOWN
            device.add_interface(iface)
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = iface_name
        return ""

    def _cmd_enter_loopback(self, tokens: list[str]) -> str:
        # tokens: ['interface', 'loopback', '<id>']
        if len(tokens) < 3:
            return "% Incomplete command."
        try:
            lb_id = int(tokens[2])
        except ValueError:
            return f"% Invalid loopback ID: {tokens[2]!r}"
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        iface_name = f"Loopback{lb_id}"
        if iface_name not in device.interfaces:
            iface = Interface(
                name=iface_name,
                mac=_virtual_iface_mac(self.device_id, iface_name),
            )
            device.add_interface(iface)
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = iface_name
        return ""

    def _cmd_ip_address(self, tokens: list[str]) -> str:
        # tokens: ['ip', 'address', '<ip>', '<mask>']
        if len(tokens) < 4:
            return "% Incomplete command.\nUsage: ip address <ip-address> <subnet-mask>"
        ip_str, mask_str = tokens[2], tokens[3]
        try:
            ip = IPv4Address(ip_str)
        except ValueError:
            return _invalid_at(" ".join(tokens[:3]), tokens[2])
        try:
            mask_int = int(IPv4Address(mask_str))
        except ValueError:
            # IOS takes a dotted mask only (no "/24" or "24")
            return _invalid_at(" ".join(tokens[:4]), tokens[3])
        prefix = _mask_prefix(mask_int)
        if prefix is None:
            return f"% Bad mask 0x{mask_int:X} for address {ip}"
        if not _is_valid_host_address(ip):
            return f"Not a valid host address - {ip}"
        cidr = f"{ip}/{prefix}"
        overlap = self._overlapping_interface(IPv4Network(cidr, strict=False))
        if overlap is not None:
            net = IPv4Network(cidr, strict=False).network_address
            return f"% {net} overlaps with {_long_name(overlap)}"
        iface = self._get_current_iface()
        if iface is not None and iface.is_subinterface and iface.dot1q_vlan is None:
            return ("% Configuring IP routing on a LAN subinterface is only allowed if that\n"
                    "subinterface is already configured as part of an IEEE 802.10, IEEE 802.1Q,\n"
                    "or ISL vLAN.")
        if iface:
            try:
                iface.set_ip(cidr)
            except Exception as exc:
                return f"% {exc}"
        self._refresh_l3()
        return ""

    def _cmd_encapsulation_dot1q(self, tokens: list[str]) -> str:
        # tokens: ['encapsulation', 'dot1Q', '<vlan>', ['native']]
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        if not iface.is_subinterface:
            return ("% Configuring IEEE 802.1Q encapsulation on the main "
                    "interface is not supported")
        if len(tokens) < 3:
            return "% Incomplete command."
        try:
            vlan = int(tokens[2])
        except ValueError:
            return _invalid_at(" ".join(tokens[:3]), tokens[2])
        if not 1 <= vlan <= 4094:
            return _invalid_at(" ".join(tokens[:3]), tokens[2])
        native = len(tokens) > 3 and "native".startswith(tokens[3].lower())
        if len(tokens) > 3 and not native:
            return _invalid_at(" ".join(tokens[:4]), tokens[3])
        device = self.simulation.topology.devices[self.device_id]
        for other in device.interfaces.values():
            if (other is not iface and other.is_subinterface
                    and other.parent_name == iface.parent_name
                    and other.dot1q_vlan == vlan):
                return (f"% Configuration of multiple subinterfaces of the same main\n"
                        f"% interface with the same VID ({vlan}) is not permitted.\n"
                        f"% This VID is already configured on {_long_name(other.name)}.")
        iface.dot1q_vlan = vlan
        iface.dot1q_native = native
        return ""

    def _overlapping_interface(self, network: IPv4Network) -> Optional[str]:
        """
        Name of another interface on this device whose subnet overlaps
        *network* (IOS refuses overlapping subnets on one router), or None.
        """
        device = self.simulation.topology.devices.get(self.device_id)
        if device is None:
            return None
        for name, other in device.interfaces.items():
            if name == self.current_iface or other.ip_config is None:
                continue
            if other.ip_config.network.overlaps(network):
                return name
        return None

    def _cmd_no_ip_address(self, tokens: list[str]) -> str:
        iface = self._get_current_iface()
        if iface:
            iface.ip_config = None
        self._refresh_l3()
        return ""

    def _cmd_shutdown(self, tokens: list[str]) -> str:
        from simulator_core.types import InterfaceState
        iface = self._get_current_iface()
        if iface:
            iface.admin_state = InterfaceState.DOWN
            # "shutdown" (then "no shutdown") is how IOS recovers a port
            # from err-disable by hand.
            iface.err_disabled = None
        self._refresh_l3()
        return ""

    def _cmd_no_shutdown(self, tokens: list[str]) -> str:
        from simulator_core.types import InterfaceState
        iface = self._get_current_iface()
        if iface:
            iface.admin_state = InterfaceState.UP
        self._refresh_l3()
        return ""

    def _cmd_description(self, tokens: list[str]) -> str:
        iface = self._get_current_iface()
        if iface and len(tokens) > 1:
            iface._description = " ".join(tokens[1:])  # type: ignore[attr-defined]
        return ""

    def _cmd_no_description(self, tokens: list[str]) -> str:
        iface = self._get_current_iface()
        if iface:
            iface._description = ""  # type: ignore[attr-defined]
        return ""

    def _cmd_iface_speed(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        # Speed is only valid on physical ports.
        if iface.is_svi or iface.is_loopback:
            return (
                _invalid("speed")
                + "\n% 'speed' is not supported on logical interfaces (SVI, Loopback)."
            )
        val = tokens[1].lower()
        if val == "auto":
            from simulator_core.port_types import detect_port_type
            pt = detect_port_type(iface.name)
            iface.speed_kbps = pt.speed_kbps
        else:
            try:
                mbps = int(val)
                iface.speed_kbps = mbps * 1000
            except ValueError:
                return f"% Invalid speed: {val!r}\n  Valid: 10, 100, 1000, 10000, auto"
        # Update STP cost if port is in STP
        switch = self._get_switch()
        if switch:
            from simulator_core.port_types import detect_port_type
            pt = detect_port_type(iface.name)
            cost = iface.speed_kbps and _speed_to_stp_cost(iface.speed_kbps) or pt.stp_cost_short
            for inst in switch.stp.all_instances():
                port = switch.stp._get_or_create_port(inst, self.current_iface or "")
                port.path_cost = cost
        return ""

    def _cmd_iface_duplex(self, tokens: list[str], mode: str) -> str:
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        # Duplex is only valid on physical ports.
        if iface.is_svi or iface.is_loopback:
            return (
                _invalid("duplex")
                + "\n% 'duplex' is not supported on logical interfaces (SVI, Loopback)."
            )
        iface.duplex = mode
        return ""

    def _cmd_show_interfaces_status(self, tokens: list[str]) -> str:
        """show interfaces status — brief port status table with speed/type."""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        from simulator_core.types import InterfaceState
        from simulator_core.port_types import detect_port_type, format_speed

        switch = self._get_switch()
        if len(tokens) > 3:
            if not "err-disabled".startswith(tokens[3].lower()):
                return _invalid_at(" ".join(tokens[:4]), tokens[3])
            rows = ["Port      Name               Status       Reason               Err-disabled Vlans"]
            for name in _display_order(device):
                iface = device.interfaces[name]
                if iface.is_physical_switchport and iface.err_disabled:
                    desc = getattr(iface, "_description", "")[:18]
                    rows.append(f"{name:<9} {desc:<18} {'err-disabled':<12} {iface.err_disabled}")
            return "\n".join(rows)
        lines = [
            "Port      Name               Status       Vlan       Duplex  Speed Type",
        ]
        for name in _display_order(device):
            iface = device.interfaces[name]
            if not iface.is_physical_switchport:
                continue
            status = _switch_port_status(iface, switch.vlans if switch else None)
            mode = iface.oper_switchport_mode
            if mode == "trunk":
                vlan_field = "trunk"
            elif mode == "access":
                vlan_field = str(iface.vlan)
            else:
                vlan_field = "routed"
            desc = getattr(iface, "_description", "")[:18]
            pt = detect_port_type(name)
            mbps = (iface.speed_kbps or pt.speed_kbps or 0) // 1000
            if status == "connected":
                duplex_str = "a-full" if iface.duplex == "auto" else iface.duplex
                speed_str = f"a-{mbps}"
            else:
                duplex_str = "auto" if iface.duplex == "auto" else iface.duplex
                speed_str = "auto"
            lines.append(
                f"{name:<9} {desc:<18} {status:<12} {vlan_field:<10} {duplex_str:>6} {speed_str:>5} {_media_type(name)}"
            )
        return "\n".join(lines)

    def _show_ip_iface_dispatch(self, tokens: list[str]) -> str:
        """Dispatch 'show ip interface <name>' with fuzzy match."""
        # tokens: ['show', 'ip', 'interface', <name>...]
        tokens = _join_iface_tokens(tokens, 3)
        if len(tokens) <= 3:
            return self._cmd_show_ip_int_brief(tokens)
        if "brief".startswith(tokens[3].lower()):
            return self._cmd_show_ip_int_brief(tokens)
        device = self.simulation.topology.devices.get(self.device_id)
        if device:
            matches = _match_iface(tokens[3], list(device.interfaces.keys()))
            if len(matches) == 1:
                return self._cmd_show_ip_iface(tokens, matches[0])
        return _invalid_at(" ".join(tokens[:4]), tokens[3])

    def _show_interfaces_dispatch(self, tokens: list[str]) -> str:
        """Dispatch 'show interfaces [<name>]' with fuzzy match."""
        tokens = _join_iface_tokens(tokens, 2)
        if len(tokens) < 3:
            return self._cmd_show_interfaces_all(tokens)
        sub = tokens[2].lower()
        if sub in ("brief", "bri", "br"):
            return self._cmd_show_ip_int_brief(tokens)
        # Type-aware match on interface name
        device = self.simulation.topology.devices.get(self.device_id)
        if device:
            matches = _match_iface(tokens[2], list(device.interfaces.keys()))
            if len(matches) == 1:
                return self._cmd_show_interface(tokens, matches[0])
        return _invalid_at(" ".join(tokens[:3]), tokens[2])

    def _cmd_show_ip_int_brief(self, tokens: list[str]) -> str:
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        lines = [
            "Interface              IP-Address      OK? Method Status                Protocol",
        ]
        for name in _display_order(device):
            iface = device.interfaces[name]
            ip     = str(iface.ip_config.address) if iface.ip_config else "unassigned"
            method = "manual" if iface.ip_config else "unset"
            status, proto = _status_words(iface)
            lines.append(
                f"{_long_name(name):<22} {ip:<15} YES {method:<6} {status:<21} {proto}"
            )
        return "\n".join(lines)

    def _cmd_show_ip_iface(self, tokens: list[str], iface_name: str) -> str:
        """show ip interface <name>"""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        iface = device.interfaces.get(iface_name)
        if not iface:
            return f"% Interface {iface_name!r} not found."
        from simulator_core.types import InterfaceState
        status, proto = _status_words(iface)
        lines = [
            f"{_long_name(iface_name)} is {status}, line protocol is {proto}",
        ]
        if iface.ip_config:
            net = iface.ip_config.network
            lines.append(f"  Internet address is {iface.ip_config.address}/{iface.ip_config.prefix_length}")
            lines.append(f"  Broadcast address is {iface.ip_config.broadcast}")
            lines.append(f"  Address determined by manual")
            lines.append(f"  MTU is 1500 bytes")
            lines.append(f"  Helper address is not set")
            lines.append(f"  Directed broadcast forwarding is disabled")
            lines.append(f"  Outgoing access list is not set")
            lines.append(f"  Inbound  access list is not set")
        else:
            lines.append("  Internet protocol processing disabled")
        lines.append(f"  ICMP redirects are always sent")
        lines.append(f"  ICMP unreachables are always sent")
        lines.append(f"  {iface.rx_frames} packets input, {iface.tx_frames} packets output")
        return "\n".join(lines)

    def _cmd_show_interfaces_all(self, tokens: list[str]) -> str:
        """show interfaces — all interfaces."""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        return "\n".join(self._iface_block(name) for name in _display_order(device))

    def _cmd_show_interface(self, tokens: list[str], iface_name: str) -> str:
        """show interfaces <name> [switchport]"""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        if iface_name not in device.interfaces:
            return f"% Interface {iface_name!r} not found."
        extra = _join_iface_tokens(tokens, 2)[3:]
        if extra:
            if "switchport".startswith(extra[0].lower()) and len(extra) == 1:
                return self._cmd_show_switchport(iface_name)
            return _invalid_at(" ".join(_join_iface_tokens(tokens, 2)[:4]), extra[0])
        return self._iface_block(iface_name)

    def _iface_block(self, iface_name: str) -> str:
        from simulator_core.types import InterfaceState
        from ipaddress import IPv4Network as _Net
        from simulator_core.port_types import detect_port_type, format_speed
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return ""
        iface = device.interfaces.get(iface_name)
        if not iface:
            return ""
        from simulator_core.types import DeviceModel
        status, proto = _status_words(iface)
        desc  = getattr(iface, "_description", "")
        port_type = detect_port_type(iface_name)
        speed_kbps = iface.speed_kbps or port_type.speed_kbps or 0
        header = f"{_long_name(iface_name)} is {status}, line protocol is {proto}"
        if device.model == DeviceModel.SWITCH and iface.is_physical_switchport:
            switch = self._get_switch()
            header += f" ({_switch_port_status(iface, switch.vlans if switch else None)})"
        lines = [header]
        mac = _cisco_mac(iface.mac)
        lines.append(f"  Hardware is {_hardware_name(iface_name)}, address is {mac} (bia {mac})")
        if desc:
            lines.append(f"  Description: {desc}")
        if iface.ip_config:
            lines.append(f"  Internet address is {iface.ip_config.address}/{iface.ip_config.prefix_length}")
        bw = speed_kbps if speed_kbps else 8000000
        lines.append(f"  MTU 1500 bytes, BW {bw} Kbit/sec, DLY 100 usec,")
        lines.append(f"     reliability 255/255, txload 1/255, rxload 1/255")
        if iface.is_subinterface and iface.dot1q_vlan is not None:
            lines.append(f"  Encapsulation 802.1Q Virtual LAN, Vlan ID  {iface.dot1q_vlan}.")
        else:
            lines.append(f"  Encapsulation ARPA, loopback not set")
        if port_type.is_physical and not iface.is_subinterface:
            if iface.oper_state == InterfaceState.UP:
                lines.append(f"  Full-duplex, {speed_kbps // 1000}Mb/s, media type is {_media_type(iface_name)}")
            else:
                lines.append(f"  Auto-duplex, Auto-speed, media type is {_media_type(iface_name)}")
        lines.append(f"     {iface.rx_frames} packets input,  0 bytes,  0 no buffer")
        lines.append(f"     Received 0 broadcasts, 0 runts, 0 giants, 0 throttles")
        lines.append(f"     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored")
        lines.append(f"     {iface.tx_frames} packets output, 0 bytes, 0 underruns")
        return "\n".join(lines)
