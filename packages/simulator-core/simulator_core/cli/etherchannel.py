"""
EtherChannel: ``channel-group`` and ``show etherchannel``.
"""

from __future__ import annotations



class EtherChannelCommands:
    """EtherChannel: ``channel-group`` and ``show etherchannel``. (mixed into ``CLISession``)."""

    def _cmd_channel_group(self, tokens: list[str]) -> str:
        """
        channel-group <1-6> mode <on|active|passive|desirable|auto>

        Enforces LACP and PAgP compatibility rules:
          LACP: at least one side must be 'active'
          PAgP: at least one side must be 'desirable'
          Static: both sides must use 'on'
        """
        if len(tokens) < 4:
            return "% Incomplete command.\nUsage: channel-group <1-6> mode <on|active|passive|desirable|auto>"
        switch = self._get_switch()
        if switch is None:
            return "% channel-group is only available on switch devices."
        try:
            group_id = int(tokens[1])
            if not (1 <= group_id <= 6):
                return "% Channel group ID must be 1-6."
        except ValueError:
            return f"% Invalid group ID: {tokens[1]!r}"
        if tokens[2].lower() != "mode":
            return "% Expected 'mode' after channel-group ID."
        valid_modes = {"on", "active", "passive", "desirable", "auto"}
        proto = tokens[3].lower()
        if proto not in valid_modes:
            return (
                f"% Invalid mode: {tokens[3]!r}\n"
                f"  Valid modes: on, active, passive (LACP), desirable, auto (PAgP)"
            )
        iface_name = self.current_iface
        if iface_name is None:
            return "% No interface selected."

        pc = switch.add_port_channel(group_id, iface_name, proto)

        # Warn if mode may not bundle without the right peer
        from simulator_core.devices.switch import protocols_compatible
        warnings = []
        if proto == "passive":
            warnings.append(
                "% Warning: LACP 'passive' mode requires the peer to be 'active'.\n"
                "  passive + passive = no bundle. Configure peer as 'active'."
            )
        elif proto == "auto":
            warnings.append(
                "% Warning: PAgP 'auto' mode requires the peer to be 'desirable'.\n"
                "  auto + auto = no bundle. Configure peer as 'desirable'."
            )

        return "\n".join(warnings) if warnings else ""

    def _cmd_show_etherchannel_summary(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show etherchannel is only available on switch devices."
        pcs = switch.port_channels
        if not pcs:
            return "% No EtherChannel groups configured."
        flags = (
            "Flags:  D - down        P - bundled in port-channel\n"
            "        I - stand-alone s - suspended\n"
            "        H - Hot-standby (LACP only)\n"
            "        R - Layer3      S - Layer2\n"
            "        U - in use      f - failed to allocate aggregator\n"
            "        M - not in use, minimum links not met\n"
            "        u - unsuitable for bundling\n"
        )
        lines = [
            flags,
            "Number of channel-groups in use: " + str(len(pcs)),
            "Group  Port-channel  Protocol    Ports",
            "------+-------------+-----------+-----------------------------------------------",
        ]
        for gid, pc in sorted(pcs.items()):
            proto_map = {
                "on":        "        -",
                "active":    "    LACP",
                "passive":   "    LACP",
                "desirable": "    PAgP",
                "auto":      "    PAgP",
            }
            proto_str = proto_map.get(pc.protocol, "        -")
            status = pc.status_flags
            members_str = " ".join(f"{m}({pc.member_flags})" for m in pc.members) if pc.members else "(none)"
            # Show negotiation warning if bundle is not up
            if not pc.is_operationally_up and pc.protocol != "on":
                _, reason = protocols_compatible(pc.protocol, pc._peer_protocol or "unknown")
                members_str += f"  ← {reason[:60]}"
            lines.append(
                f"{gid:<6} {pc.name}({status}){' ' * (11 - len(pc.name) - len(status))} {proto_str:<11} {members_str}"
            )
        return "\n".join(lines)

    def _cmd_show_etherchannel_detail(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show etherchannel is only available on switch devices."
        pcs = switch.port_channels
        if not pcs:
            return "% No EtherChannel groups configured."
        lines = []
        for gid, pc in sorted(pcs.items()):
            lines += [
                f"Group state = L2",
                f"Ports: {len(pc.members)}  Maxports = 8",
                f"Port-channels: 1 Max Port-channels = 1",
                f"Protocol: {'LACP' if pc.protocol in ('active','passive') else 'PAgP' if pc.protocol in ('desirable','auto') else 'None'}",
                f"Minimum Links: 0",
                f"",
                f"                Ports in the group:",
                f"                -------------------",
                f" Port: {pc.name}",
                f"------------",
                f"Age of the Port-channel   = 0d:00h:00m:00s",
                f"Logical slot/port   = 1/{gid}  Number of ports = {len(pc.members)}",
                f"HotStandBy port = null",
                f"Port state          = Port-channel Ag-Inuse",
                f"Protocol            =   {'LACP' if pc.protocol in ('active','passive') else 'PAgP' if pc.protocol in ('desirable','auto') else 'None'}",
                f"Port security       = Disabled",
                f"",
            ]
            for m in pc.members:
                lines.append(f"  Port: {m}")
                lines.append(f"  ---")
                lines.append(f"  Age of the port in the current state: 0d:00h:00m:00s")
                lines.append(f"  Port state          = Up Mstr Assoc In-Bndl")
                lines.append(f"  Channel group       = {gid}  Mode = {'Active' if pc.protocol == 'active' else 'Passive' if pc.protocol == 'passive' else pc.protocol.capitalize()}")
                lines.append(f"  Port-channel        = Po{gid}")
                lines.append(f"")
        return "\n".join(lines)

    def _cmd_show_etherchannel_neighbors(self, tokens: list[str]) -> str:
        """show etherchannel neighbors — LACP/PAgP neighbor information."""
        switch = self._get_switch()
        if switch is None:
            return "% show etherchannel is only available on switch devices."
        pcs = switch.port_channels
        if not pcs:
            return "% No EtherChannel groups configured."

        lines = []
        for gid, pc in sorted(pcs.items()):
            from simulator_core.devices.switch import EtherChannelProtocol
            proto = pc.lacp_protocol
            if proto == EtherChannelProtocol.LACP:
                lines.append(f"Channel group {gid}  LACP role: {'Initiator' if pc.protocol == 'active' else 'Responder'}")
                lines.append(f"  {'Port':<10} {'Flags':<6} {'State':<12} {'Priority':<10} {'Dev ID':<20}")
                lines.append(f"  {'-'*60}")
                for m in pc.members:
                    flags = "SA" if pc.protocol == "active" else "SP"  # S=LACP,A=active/P=passive
                    state = "bundled" if pc.is_operationally_up else "suspended"
                    lines.append(f"  {m:<10} {flags:<6} {state:<12} {'32768':<10} {'(no LACPDU received)':<20}")
            elif proto == EtherChannelProtocol.PAGP:
                lines.append(f"Channel group {gid}  PAgP role: {'Desirable' if pc.protocol == 'desirable' else 'Auto'}")
                lines.append(f"  {'Port':<10} {'Flags':<6} {'State':<12} {'Hello':<10}")
                lines.append(f"  {'-'*50}")
                for m in pc.members:
                    flags = "D" if pc.protocol == "desirable" else "A"
                    state = "bundled" if pc.is_operationally_up else "suspended"
                    lines.append(f"  {m:<10} {flags:<6} {state:<12} {'1':<10}")
            else:
                lines.append(f"Channel group {gid}  Mode: Static (on)")
                for m in pc.members:
                    lines.append(f"  {m} — static bundled")
            lines.append("")

        if not pc.is_operationally_up:
            compatible, reason = protocols_compatible(
                pc.protocol, pc._peer_protocol or "unknown"
            )
            if not compatible:
                lines.append(f"% Note: Group {gid} is NOT operationally up.")
                lines.append(f"% Reason: {reason}")

        return "\n".join(lines)
