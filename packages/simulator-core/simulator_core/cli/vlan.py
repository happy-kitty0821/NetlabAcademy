"""
VLANs, access ports, 802.1Q trunks and DTP, ``show vlan`` and
``show interfaces trunk / switchport``.
"""

from __future__ import annotations

from typing import Optional

from simulator_core.types import InterfaceState
from simulator_core.cli.engine import CLIMode, _invalid_at
from simulator_core.cli.helpers import _display_order, _dtp_mode_word


class VlanCommands:
    """VLANs, access ports, 802.1Q trunks and DTP, ``show vlan`` and (mixed into ``CLISession``)."""

    def _cmd_enter_vlan(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        try:
            vlan_id = int(tokens[1])
        except ValueError:
            return f"% Invalid VLAN ID: {tokens[1]!r}"
        if not (1 <= vlan_id <= 4094):
            return f"% VLAN ID must be 1-4094, got {vlan_id}"
        switch = self._get_switch()
        if switch is None:
            return "% VLAN configuration is only available on switch devices."
        switch.create_vlan(vlan_id)
        self.mode = CLIMode.VLAN_CONFIG
        self.current_vlan = vlan_id
        return ""

    def _cmd_no_vlan(self, tokens: list[str]) -> str:
        if len(tokens) < 3:
            return "% Incomplete command."
        try:
            vlan_id = int(tokens[2])
        except ValueError:
            return f"% Invalid VLAN ID: {tokens[2]!r}"
        switch = self._get_switch()
        if switch is None:
            return "% VLAN configuration is only available on switch devices."
        try:
            switch.delete_vlan(vlan_id)
        except ValueError as exc:
            return f"% {exc}"
        return ""

    def _cmd_vlan_name(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        switch = self._get_switch()
        if switch is None or self.current_vlan is None:
            return "% Not in VLAN configuration mode."
        switch.name_vlan(self.current_vlan, " ".join(tokens[1:]))
        return ""

    def _cmd_no_vlan_name(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None or self.current_vlan is None:
            return "% Not in VLAN configuration mode."
        switch.name_vlan(self.current_vlan, f"VLAN{self.current_vlan:04d}")
        return ""

    def _cmd_switchport_mode_access(self, tokens: list[str]) -> str:
        err = self._require_physical_switchport()
        if err:
            return err
        iface = self._get_current_iface()
        if iface:
            iface.switchport_mode = "access"
        return ""

    def _cmd_switchport_mode_trunk(self, tokens: list[str]) -> str:
        """switchport mode trunk"""
        err = self._require_physical_switchport()
        if err:
            return err
        switch = self._get_switch()
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        iface.switchport_mode = "trunk"
        if iface.trunk_allowed_vlans is None:
            iface.trunk_allowed_vlans = None  # all
        if switch:
            # Update STP to know about this trunk
            for vlan_id in switch.vlans:
                switch.stp.ensure_vlan(vlan_id)
        return ""

    def _cmd_switchport_mode_dynamic(self, tokens: list[str], mode: str) -> str:
        err = self._require_physical_switchport()
        if err:
            return err
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        if iface.dtp_nonegotiate:
            return "Command rejected: Conflict between 'nonegotiate' and 'dynamic' status."
        iface.switchport_mode = f"dynamic_{mode}"
        switch = self._get_switch()
        if switch:
            for vlan_id in switch.vlans:
                switch.stp.ensure_vlan(vlan_id)
        return ""

    def _cmd_switchport_nonegotiate(self, tokens: list[str], enabled: bool) -> str:
        """[no] switchport nonegotiate -- stop (or resume) sending DTP frames."""
        err = self._require_physical_switchport()
        if err:
            return err
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        if enabled and iface.switchport_mode.startswith("dynamic_"):
            return "Command rejected: Conflict between 'nonegotiate' and 'dynamic' status."
        iface.dtp_nonegotiate = enabled
        return ""

    def _cmd_switchport_trunk_native_vlan(self, tokens: list[str]) -> str:
        err = self._require_physical_switchport()
        if err:
            return err
        # tokens: ['switchport', 'trunk', 'native', 'vlan', '<id>']
        if len(tokens) < 5:
            return "% Incomplete command."
        try:
            vlan_id = int(tokens[4])
        except ValueError:
            return f"% Invalid VLAN ID: {tokens[4]!r}"
        switch = self._get_switch()
        if switch is None:
            return "% switchport commands only on switch devices."
        try:
            switch.set_trunk_native_vlan(self.current_iface, vlan_id)
        except ValueError as exc:
            return f"% {exc}"
        return ""

    def _cmd_switchport_trunk_allowed_vlan(self, tokens: list[str]) -> str:
        err = self._require_physical_switchport()
        if err:
            return err
        # tokens: ['switchport', 'trunk', 'allowed', 'vlan', '<list-or-add-remove-except>']
        if len(tokens) < 5:
            return "% Incomplete command."
        switch = self._get_switch()
        if switch is None:
            return "% switchport commands only on switch devices."
        # Parse: add | remove | except | all | <list>
        arg = tokens[4].lower()
        mode = "set"
        vlans_str = tokens[4]
        if arg in ("add", "remove", "except"):
            mode = arg
            if len(tokens) < 6:
                return f"% Incomplete command. Expected VLAN list after {arg}."
            vlans_str = tokens[5]
        vlans = self._parse_vlan_list(vlans_str)
        if vlans is None and vlans_str.lower() != "all":
            return f"% Invalid VLAN list: {vlans_str!r}"
        try:
            switch.set_trunk_allowed_vlans(self.current_iface, vlans, mode)
        except ValueError as exc:
            return f"% {exc}"
        return ""

    def _cmd_switchport_trunk_encap(self, tokens: list[str], encap: str) -> str:
        err = self._require_physical_switchport()
        if err:
            return err
        iface = self._get_current_iface()
        if iface:
            iface.trunk_encapsulation = encap
        return ""

    def _parse_vlan_list(self, s: str) -> Optional[list]:
        """Parse a Cisco VLAN list string like '1,10,20-30' into a list of ints."""
        if s.lower() == "all":
            return None
        result: list[int] = []
        try:
            for part in s.split(","):
                part = part.strip()
                if "-" in part:
                    a, b = part.split("-", 1)
                    result.extend(range(int(a.strip()), int(b.strip()) + 1))
                else:
                    result.append(int(part))
            return sorted(set(result))
        except ValueError:
            return None

    def _cmd_switchport_access_vlan(self, tokens: list[str]) -> str:
        err = self._require_physical_switchport()
        if err:
            return err
        # tokens: ['switchport', 'access', 'vlan', '<id>']
        if len(tokens) < 4:
            return "% Incomplete command."
        try:
            vlan_id = int(tokens[3])
        except ValueError:
            return f"% Invalid VLAN ID: {tokens[3]!r}"
        switch = self._get_switch()
        if switch is None:
            return "% switchport commands are only available on switch devices."
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        if not 1 <= vlan_id <= 4094:
            return _invalid_at(" ".join(tokens[:4]), tokens[3])
        message = ""
        if vlan_id not in switch.vlans:
            # Catalyst IOS creates the VLAN rather than refusing.
            switch.create_vlan(vlan_id)
            message = f"% Access VLAN does not exist. Creating vlan {vlan_id}"
        try:
            switch.set_port_vlan(self.current_iface, vlan_id)
        except ValueError as exc:
            return f"% {exc}"
        return message

    def _cmd_no_switchport(self, tokens: list[str]) -> str:
        """
        ``no switchport <setting>`` puts just that setting back to its
        default; a bare ``no switchport`` resets the port's mode and VLAN.
        """
        iface = self._get_current_iface()
        if iface is None:
            return ""
        words = [t.lower() for t in tokens[2:]]
        if words and "access".startswith(words[0]):
            iface.vlan = 1
        elif words and "trunk".startswith(words[0]) and len(words) > 1:
            if "native".startswith(words[1]):
                iface.trunk_native_vlan = 1
            elif "allowed".startswith(words[1]):
                iface.trunk_allowed_vlans = None
        else:
            iface.vlan = 1
            iface.switchport_mode = "access"
            iface.dtp_nonegotiate = False
        return ""

    def _cmd_show_interfaces_trunk(self, tokens: list[str]) -> str:
        """show interfaces trunk — Cisco-style trunk info table.

        Only physical Layer 2 switchports configured as trunks are shown.
        SVIs (Vlan<N>) and loopbacks are excluded — they are Layer 3
        logical interfaces and cannot be trunk ports.
        """
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        switch = self._get_switch()

        trunk_ifaces = [
            (name, iface)
            for name, iface in device.interfaces.items()
            if iface.is_trunk
            and iface.is_physical_switchport  # exclude SVIs and loopbacks
        ]

        if not trunk_ifaces:
            return "% No trunk interfaces configured."

        lines = [
            "Port        Mode         Encapsulation  Status        Native vlan",
        ]
        for name, iface in trunk_ifaces:
            status = "trunking" if iface.admin_state == InterfaceState.UP else "not-trunking"
            mode_abbr = _dtp_mode_word(iface)
            lines.append(
                f"{name:<11} {mode_abbr:<12} {iface.trunk_encapsulation:<14} {status:<13} {iface.trunk_native_vlan}"
            )

        lines += ["", "Port        VLANs allowed on trunk", ]
        for name, iface in trunk_ifaces:
            allowed = iface.trunk_allowed_vlans
            if allowed is None:
                vlan_str = "1-4094"
            else:
                vlan_str = self._format_vlan_list(allowed)
            lines.append(f"{name:<11} {vlan_str}")

        if switch:
            lines += ["", "Port        VLANs allowed and active in management domain"]
            for name, iface in trunk_ifaces:
                active = switch.get_active_trunk_vlans(name)
                vlan_str = self._format_vlan_list(active) if active else "none"
                lines.append(f"{name:<11} {vlan_str}")

            lines += ["", "Port        VLANs in spanning tree forwarding state and not pruned"]
            for name, iface in trunk_ifaces:
                active = switch.get_active_trunk_vlans(name)
                forwarding = [
                    v for v in active
                    if switch.stp.is_port_forwarding(name, v)
                ]
                vlan_str = self._format_vlan_list(forwarding) if forwarding else "none"
                lines.append(f"{name:<11} {vlan_str}")

        return "\n".join(lines)

    @staticmethod
    def _format_vlan_list(vlans: list[int]) -> str:
        """Format a list of VLAN IDs as a compact Cisco-style string (e.g. '1,10,20-30')."""
        if not vlans:
            return "none"
        sorted_vlans = sorted(set(vlans))
        ranges = []
        start = end = sorted_vlans[0]
        for v in sorted_vlans[1:]:
            if v == end + 1:
                end = v
            else:
                ranges.append(f"{start}-{end}" if end > start else str(start))
                start = end = v
        ranges.append(f"{start}-{end}" if end > start else str(start))
        return ",".join(ranges)

    def _cmd_show_switchport(self, iface_name: Optional[str]) -> str:
        """show interfaces [<name>] switchport — per-port L2 settings."""
        switch = self._get_switch()
        device = self.simulation.topology.devices[self.device_id]
        if switch is None:
            return "% show interfaces switchport is only available on switch devices."
        names = [iface_name] if iface_name else [
            n for n in _display_order(device) if device.interfaces[n].is_physical_switchport
        ]
        blocks = []
        for name in names:
            iface = device.interfaces[name]
            if not iface.is_physical_switchport:
                blocks.append(f"Name: {name}\nSwitchport: Disabled")
                continue
            def vname(v: int) -> str:
                if v not in switch.vlans:
                    return "Inactive"
                return switch.vlans[v] or ("default" if v == 1 else f"VLAN{v:04d}")
            admin = {"trunk": "trunk", "dynamic_auto": "dynamic auto",
                     "dynamic_desirable": "dynamic desirable"}.get(
                         iface.switchport_mode, "static access")
            if iface.oper_state != InterfaceState.UP:
                oper = "down"
            else:
                oper = "trunk" if iface.is_trunk else "static access"
            encap = "dot1q" if iface.is_trunk else "native"
            # DTP runs on trunk and dynamic ports unless nonegotiate is set.
            negotiation = ("On" if iface.switchport_mode != "access"
                           and not iface.dtp_nonegotiate else "Off")
            allowed = ("ALL" if iface.trunk_allowed_vlans is None
                       else self._format_vlan_list(sorted(iface.trunk_allowed_vlans)))
            blocks.append("\n".join([
                f"Name: {name}",
                "Switchport: Enabled",
                f"Administrative Mode: {admin}",
                f"Operational Mode: {oper}",
                "Administrative Trunking Encapsulation: dot1q",
                f"Operational Trunking Encapsulation: {encap}",
                f"Negotiation of Trunking: {negotiation}",
                f"Access Mode VLAN: {iface.vlan} ({vname(iface.vlan)})",
                f"Trunking Native Mode VLAN: {iface.trunk_native_vlan} ({vname(iface.trunk_native_vlan)})",
                "Voice VLAN: none",
                f"Trunking VLANs Enabled: {allowed}",
                "Pruning VLANs Enabled: 2-1001",
                "Protected: false",
            ]))
        return "\n\n".join(blocks)

    # Factory-default VLANs present on every Catalyst switch.
    _LEGACY_VLANS = [
        (1002, "fddi-default", "fddi"),
        (1003, "token-ring-default", "tr"),
        (1004, "fddinet-default", "fdnet"),
        (1005, "trnet-default", "trnet"),
    ]

    def _vlan_rows(self, switch) -> list[tuple[int, str, str, list[str]]]:
        """(vlan, name, status, access ports) for show vlan, IOS-ordered."""
        device = self.simulation.topology.devices[self.device_id]
        rows = []
        for vlan_id in sorted(switch.vlans):
            # IOS lists only access ports here; trunks appear in
            # "show interfaces trunk".
            ports = [
                n for n in _display_order(device)
                if device.interfaces[n].is_physical_switchport
                and device.interfaces[n].is_access
                and device.interfaces[n].vlan == vlan_id
            ]
            rows.append((vlan_id, switch.vlans[vlan_id] or f"VLAN{vlan_id:04d}", "active", ports))
        for vlan_id, name, _ in self._LEGACY_VLANS:
            rows.append((vlan_id, name, "act/unsup", []))
        return rows

    @staticmethod
    def _wrap_ports(ports: list[str]) -> list[str]:
        """IOS wraps the Ports column at about 31 characters."""
        chunks, line = [], ""
        for port in ports:
            piece = port if not line else f"{line}, {port}"
            if line and len(piece) > 31:
                chunks.append(line + ",")
                line = port
            else:
                line = piece
        if line:
            chunks.append(line)
        return chunks or [""]

    def _cmd_show_vlan_brief(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show vlan is only available on switch devices."
        lines = [
            "",
            "VLAN Name                             Status    Ports",
            "---- -------------------------------- --------- -------------------------------",
        ]
        for vlan_id, name, status, ports in self._vlan_rows(switch):
            chunks = self._wrap_ports(ports)
            lines.append(f"{vlan_id:<4} {name:<32} {status:<9} {chunks[0]}".rstrip())
            for extra in chunks[1:]:
                lines.append(f"{'':48}{extra}")
        return "\n".join(lines)

    def _cmd_show_vlan(self, tokens: list[str]) -> str:
        """show vlan: the brief table followed by the VLAN type table."""
        switch = self._get_switch()
        if switch is None:
            return "% show vlan is only available on switch devices."
        lines = [self._cmd_show_vlan_brief(tokens), "",
                 "VLAN Type  SAID       MTU   Parent RingNo BridgeNo Stp  BrdgMode Trans1 Trans2",
                 "---- ----- ---------- ----- ------ ------ -------- ---- -------- ------ ------"]
        legacy_types = {v: t for v, _, t in self._LEGACY_VLANS}
        for vlan_id, _, _, _ in self._vlan_rows(switch):
            vtype = legacy_types.get(vlan_id, "enet")
            lines.append(f"{vlan_id:<4} {vtype:<5} {100000 + vlan_id:<10} 1500  -      -      -        -    -        0      0")
        return "\n".join(lines)
