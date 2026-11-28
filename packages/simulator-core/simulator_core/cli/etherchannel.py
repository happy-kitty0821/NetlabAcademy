"""
EtherChannel: ``channel-group``, ``interface port-channel``, load balancing
and the ``show etherchannel`` / ``show lacp`` / ``show pagp`` family.
"""

from __future__ import annotations

from simulator_core.cli.engine import Cmd, _int_in, _invalid_at
from simulator_core.cli.helpers import _cisco_mac
from simulator_core.l2.etherchannel import (
    DEFAULT_LOAD_BALANCE,
    LOAD_BALANCE_METHODS,
    MAX_GROUP,
    PAGP_MODES,
    LACP_MODES,
    protocol_label,
    protocol_of,
)

_MODE_HELP = {
    "active": "Enable LACP unconditionally",
    "auto": "Enable PAgP only if a PAgP device is detected",
    "desirable": "Enable PAgP unconditionally",
    "on": "Enable Etherchannel only",
    "passive": "Enable LACP only if a LACP device is detected",
}
_LB_HELP = {
    "dst-ip": "Dst IP Addr",
    "dst-mac": "Dst Mac Addr",
    "src-dst-ip": "Src XOR Dst IP Addr",
    "src-dst-mac": "Src XOR Dst Mac Addr",
    "src-ip": "Src IP Addr",
    "src-mac": "Src Mac Addr",
}
_LB_WORDS = {
    "src-mac": ("Source MAC address", "Source MAC address"),
    "dst-mac": ("Destination MAC address", "Destination MAC address"),
    "src-dst-mac": ("Source XOR Destination MAC address", "Source XOR Destination MAC address"),
    "src-ip": ("Source MAC address", "Source IP address"),
    "dst-ip": ("Destination MAC address", "Destination IP address"),
    "src-dst-ip": ("Source XOR Destination MAC address", "Source XOR Destination IP address"),
}


def _channel_group_tree() -> "Cmd":
    """``channel-group <1-6> mode <mode>`` on a physical interface."""
    run = lambda s, t: s._cmd_channel_group(t)  # noqa: E731
    return Cmd("channel-group", "Etherchannel/port bundling configuration", children=[
        Cmd(f"<1-{MAX_GROUP}>", "Channel group number", arg=_int_in(1, MAX_GROUP), children=[
            Cmd("mode", "Etherchannel Mode of the interface", children=[
                Cmd(mode, help_str, handler=run) for mode, help_str in _MODE_HELP.items()
            ]),
        ]),
    ])


def _load_balance_tree(negate: bool) -> "Cmd":
    """``[no] port-channel load-balance <method>`` in global configuration."""
    run = lambda s, t: s._cmd_port_channel_load_balance(t, negate)  # noqa: E731
    return Cmd("port-channel", "EtherChannel configuration", children=[
        Cmd("load-balance", "EtherChannel load-balancing method",
            handler=run if negate else None,
            children=[Cmd(m, _LB_HELP[m], handler=run) for m in LOAD_BALANCE_METHODS]),
    ])


def _no_interface_tree() -> "Cmd":
    """``no interface port-channel <1-6>``."""
    return Cmd("interface", "Delete a logical interface", children=[
        Cmd("port-channel", "Ethernet Channel of interfaces", children=[
            Cmd(f"<1-{MAX_GROUP}>", "Port-channel interface number",
                arg=_int_in(1, MAX_GROUP),
                handler=lambda s, t: s._cmd_no_interface_port_channel(t)),
        ]),
    ])


_SUMMARY_FLAGS = [
    "Flags:  D - down        P - bundled in port-channel",
    "        I - stand-alone s - suspended",
    "        H - Hot-standby (LACP only)",
    "        R - Layer3      S - Layer2",
    "        U - in use      f - failed to allocate aggregator",
    "",
    "        M - not in use, minimum links not met",
    "        u - unsuitable for bundling",
    "        w - waiting to be aggregated",
    "        d - default port",
    "",
]


class EtherChannelCommands:
    """EtherChannel commands (mixed into ``CLISession``)."""

    # ── configuration ─────────────────────────────────────────────────────────

    def _cmd_channel_group(self, tokens: list[str]) -> str:
        """channel-group <1-6> mode <on|active|passive|desirable|auto>"""
        switch = self._get_switch()
        if switch is None:
            return "% channel-group is only available on switch devices."
        iface = self._get_current_iface()
        name = self.current_iface
        if iface is None or iface.is_port_channel or not iface.is_physical_switchport:
            return _invalid_at("channel-group", "channel-group")
        group_id = int(tokens[1])
        mode = next(m for m in _MODE_HELP if m.startswith(tokens[3].lower()))
        existing = switch.port_channels.get(group_id)
        if existing is not None:
            others = [m for m in existing.members if m != name]
            if others and protocol_of(existing.protocol) != protocol_of(mode):
                return (f"Command rejected (Channel protocol mismatch for interface {name} "
                        f"in group {group_id}): the interface can not be added to the "
                        f"channel group")
        created = f"Po{group_id}" not in self.simulation.topology.devices[self.device_id].interfaces
        switch.add_port_channel(group_id, name, mode)
        return f"Creating a port-channel interface Port-channel {group_id}" if created else ""

    def _cmd_no_channel_group(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is not None and self.current_iface:
            switch.remove_port_channel_member(self.current_iface)
        return ""

    def _cmd_no_interface_port_channel(self, tokens: list[str]) -> str:
        """no interface port-channel N"""
        switch = self._get_switch()
        if switch is None:
            return "% port-channel interfaces exist only on switch devices."
        switch.remove_port_channel(int(tokens[-1]))
        return ""

    def _cmd_port_channel_load_balance(self, tokens: list[str], negate: bool) -> str:
        """[no] port-channel load-balance <method>"""
        switch = self._get_switch()
        if switch is None:
            return "% port-channel load-balance is only available on switch devices."
        if negate:
            switch.load_balance = DEFAULT_LOAD_BALANCE
            return ""
        # The command tree has already matched the (possibly abbreviated)
        # method keyword uniquely.
        word = tokens[-1].lower()
        switch.load_balance = word if word in LOAD_BALANCE_METHODS else next(
            m for m in LOAD_BALANCE_METHODS if m.startswith(word))
        return ""

    def _enter_port_channel(self, number: str) -> str:
        """interface port-channel N: create it if needed and enter it."""
        switch = self._get_switch()
        if switch is None:
            return "% port-channel interfaces exist only on switch devices."
        if not number.isdigit() or not 1 <= int(number) <= MAX_GROUP:
            return f"% Invalid interface name: 'port-channel{number}'"
        pc, _created = switch.ensure_port_channel(int(number))
        from simulator_core.cli.engine import CLIMode
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = pc.short
        self.current_range = []
        return ""

    # ── show ──────────────────────────────────────────────────────────────────

    def _cmd_show_etherchannel_summary(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show etherchannel is only available on switch devices."
        pcs = switch.port_channels
        lines = _SUMMARY_FLAGS + [
            "",
            f"Number of channel-groups in use: {len(pcs)}",
            f"Number of aggregators:           {len(pcs)}",
            "",
            "Group  Port-channel  Protocol    Ports",
            "------+-------------+-----------+-----------------------------------------------",
        ]
        for gid, pc in sorted(pcs.items()):
            ports = "".join(f"{m}({pc.member_flag(m)})".ljust(12) for m in pc.members).rstrip()
            label = f"{pc.short}({pc.status_flags})"
            lines.append(f"{gid:<7}{label:<16}{protocol_label(pc.protocol):<10}{ports}")
        return "\n".join(lines)

    def _port_state_words(self, pc, port: str) -> str:
        return {"P": "Up Mstr Assoc In-Bndl", "I": "Up Indep", "s": "Up Mstr Susp-Bndl",
                "D": "Down Not-Bndl"}.get(pc.member_flag(port), "Down Not-Bndl")

    def _age(self, since: float) -> str:
        secs = max(0, int(self.simulation.lab_time - since))
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m, s = divmod(rem, 60)
        return f"{d}d:{h:02d}h:{m:02d}m:{s:02d}s"

    def _cmd_show_etherchannel_detail(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show etherchannel is only available on switch devices."
        pcs = switch.port_channels
        lines = ["                Channel-group listing:", "                ----------------------", ""]
        for gid, pc in sorted(pcs.items()):
            proto = protocol_label(pc.protocol)
            maxports = 16 if pc.protocol in LACP_MODES else 8
            lines += [
                f"Group: {gid}", "----------",
                "Group state = L2",
                f"Ports: {len(pc.members)}   Maxports = {maxports}",
                "Port-channels: 1 Max Port-channels = 1",
                f"Protocol:   {proto}",
                "Minimum Links: 0",
                "", "",
                "                Ports in the group:",
                "                -------------------",
            ]
            for index, m in enumerate(pc.members):
                iface = self.simulation.topology.devices[self.device_id].interfaces[m]
                mode = (iface.channel_mode or "on").capitalize()
                lines += [
                    f"Port: {m}", "------------", "",
                    f"Port state    = {self._port_state_words(pc, m)}",
                    f"Channel group = {gid:<12}Mode = {mode:<15}Gcchange = -",
                    f"Port-channel  = {pc.short:<12}GC   =   -             Pseudo port-channel = {pc.short}",
                    f"Port index    = {index:<12}Load = 0x00            Protocol = {proto:>6}",
                    "",
                ]
            lines += self._port_channel_block(pc)
        return "\n".join(lines).rstrip()

    def _port_channel_block(self, pc) -> list[str]:
        po = self.simulation.topology.devices[self.device_id].interfaces[pc.short]
        state = "Port-channel Ag-Inuse" if pc.bundled else "Port-channel Ag-Not-Inuse"
        lines = [
            "                Port-channels in the group:",
            "                ---------------------------",
            "",
            f"Port-channel: {pc.short}" + ("    (Primary Aggregator)" if pc.protocol in LACP_MODES else ""),
            "",
            "------------",
            "",
            f"Age of the Port-channel   = {self._age(pc.created_at)}",
            f"Logical slot/port   = 2/{pc.group_id}          Number of ports = {len(pc.bundled)}",
            "HotStandBy port = null",
            f"Port state          = {state}",
            f"Protocol            = {protocol_label(pc.protocol):>6}",
            f"Port security       = {'Enabled' if po.err_disabled else 'Disabled'}",
            "",
            "Ports in the Port-channel:",
            "",
            "Index   Load   Port     EC state        No of bits",
            "------+------+------+------------------+-----------",
        ]
        ec_state = {"active": "Active", "passive": "Passive", "desirable": "Desirable-Sl",
                    "auto": "Automatic-Sl", "on": "On"}.get(pc.protocol, "On")
        for index, m in enumerate(pc.bundled):
            lines.append(f"  {index:<6}00     {m:<9}{ec_state:<19}0")
        if pc.last_bundled:
            port, at = pc.last_bundled
            lines += ["", f"Time since last port bundled:    {self._age(at)}    {port}"]
        lines.append("")
        return lines

    def _cmd_show_etherchannel_port_channel(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show etherchannel is only available on switch devices."
        lines = ["                Channel-group listing:", "                ----------------------", ""]
        for gid, pc in sorted(switch.port_channels.items()):
            lines += [f"Group: {gid}", "----------"] + self._port_channel_block(pc)
        return "\n".join(lines).rstrip()

    def _cmd_show_etherchannel_load_balance(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show etherchannel is only available on switch devices."
        non_ip, ip = _LB_WORDS[switch.load_balance]
        return "\n".join([
            "EtherChannel Load-Balancing Configuration:",
            f"        {switch.load_balance}",
            "",
            "EtherChannel Load-Balancing Addresses Used Per-Protocol:",
            f"Non-IP: {non_ip}",
            f"  IPv4: {ip}",
            f"  IPv6: {ip}",
        ])

    def _partners(self, pc):
        """(member, peer device, peer port, peer switch) for members facing a channel."""
        topo = self.simulation.topology
        for m in pc.members:
            peer = topo.neighbours(self.device_id, m)
            if peer is None:
                continue
            try:
                peer_switch = self.simulation.get_switch(peer[0])
            except KeyError:
                continue
            peer_iface = topo.devices[peer[0]].interfaces.get(peer[1])
            if peer_iface is None or peer_iface.channel_group is None:
                continue
            yield m, topo.devices[peer[0]], peer[1], peer_iface, peer_switch

    def _cmd_show_lacp_neighbor(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show lacp is only available on switch devices."
        lines = [
            "Flags:  S - Device is requesting Slow LACPDUs",
            "        F - Device is requesting Fast LACPDUs",
            "        A - Device is in Active mode       P - Device is in Passive mode",
        ]
        for gid, pc in sorted(switch.port_channels.items()):
            if pc.protocol not in LACP_MODES:
                continue
            lines += ["", f"Channel group {gid} neighbors", "", "Partner's information:", "",
                      "                  LACP port                        Admin  Oper   Port    Port",
                      "Port      Flags   Priority  Dev ID          Age    key    Key    Number  State"]
            for m, peer_dev, peer_port, peer_iface, peer_switch in self._partners(pc):
                if peer_iface.channel_mode not in LACP_MODES or pc.member_flag(m) != "P":
                    continue
                flags = "SA" if peer_iface.channel_mode == "active" else "SP"
                number = 0x100 + int(peer_port.rsplit("/", 1)[-1])
                state = "0x3D" if peer_iface.channel_mode == "active" else "0x3C"
                lines.append(f"{m:<10}{flags:<8}32768     {_cisco_mac(peer_switch.stp._mac):<16}"
                             f"{'1s':<7}0x0    0x{peer_iface.channel_group:<5X}0x{number:<6X}{state}")
        return "\n".join(lines)

    def _cmd_show_pagp_neighbor(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show pagp is only available on switch devices."
        lines = [
            "Flags:  S - Device is sending Slow hello.  C - Device is in Consistent state.",
            "        A - Device is in Auto mode.        P - Device learns on physical port.",
        ]
        for gid, pc in sorted(switch.port_channels.items()):
            if pc.protocol not in PAGP_MODES:
                continue
            lines += ["", f"Channel group {gid} neighbors",
                      "          Partner              Partner          Partner         Partner Group",
                      "Port      Name                 Device ID        Port       Age  Flags   Cap."]
            for m, peer_dev, peer_port, peer_iface, peer_switch in self._partners(pc):
                if peer_iface.channel_mode not in PAGP_MODES or pc.member_flag(m) != "P":
                    continue
                flags = "SAC" if peer_iface.channel_mode == "auto" else "SC"
                lines.append(f"{m:<10}{peer_dev.hostname:<21}{_cisco_mac(peer_switch.stp._mac):<17}"
                             f"{peer_port:<9}{'1s':>5} {flags:<8}{10000 + peer_iface.channel_group:X}")
        return "\n".join(lines)

    def _cmd_show_etherchannel_neighbors(self, tokens: list[str]) -> str:
        """LACP and PAgP neighbour tables together."""
        return self._cmd_show_lacp_neighbor(tokens) + "\n\n" + self._cmd_show_pagp_neighbor(tokens)
