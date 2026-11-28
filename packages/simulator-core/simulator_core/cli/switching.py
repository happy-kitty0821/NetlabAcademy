"""
MAC address table, err-disable and port security.
"""

from __future__ import annotations



# Err-disable causes on a Catalyst 2960 (errdisable recovery cause ...).

from simulator_core.types import InterfaceState
from simulator_core.cli.engine import Cmd, _int_in, _invalid_at, _match, _parse_mac
from simulator_core.cli.helpers import (
    _cisco_mac,
    _display_order,
    _join_iface_tokens,
    _long_name,
    _match_iface,
    _natural_key,
)


_ERRDISABLE_CAUSES = [
    ("arp-inspection", "Enable timer to recover from arp inspection error disable state"),
    ("bpduguard", "Enable timer to recover from BPDU Guard error"),
    ("channel-misconfig", "Enable timer to recover from channel misconfig error"),
    ("dhcp-rate-limit", "Enable timer to recover from dhcp-rate-limit error"),
    ("dtp-flap", "Enable timer to recover from dtp-flap error"),
    ("gbic-invalid", "Enable timer to recover from invalid GBIC error"),
    ("inline-power", "Enable timer to recover from inline-power error"),
    ("l2ptguard", "Enable timer to recover from l2protocol-tunnel error"),
    ("link-flap", "Enable timer to recover from link-flap error"),
    ("loopback", "Enable timer to recover from loopback error"),
    ("mac-limit", "Enable timer to recover from mac limit disable state"),
    ("pagp-flap", "Enable timer to recover from pagp-flap error"),
    ("port-mode-failure", "Enable timer to recover from port mode change failure"),
    ("psecure-violation", "Enable timer to recover from psecure violation error"),
    ("security-violation", "Enable timer to recover from 802.1x violation error"),
    ("sfp-config-mismatch", "Enable timer to recover from SFP config mismatch error"),
    ("small-frame", "Enable timer to recover from small frame error"),
    ("storm-control", "Enable timer to recover from storm-control error"),
    ("udld", "Enable timer to recover from udld error"),
    ("vmps", "Enable timer to recover from vmps shutdown error"),
]


def _errdisable_tree(negate: bool) -> "Cmd":
    """``[no] errdisable recovery cause <cause>|all`` / ``interval <30-86400>``."""
    cause = lambda s, t: s._cmd_errdisable_cause(t, not negate)  # noqa: E731
    interval = lambda s, t: s._cmd_errdisable_interval(t, negate)  # noqa: E731
    causes = [Cmd(name, help_str, handler=cause) for name, help_str in _ERRDISABLE_CAUSES]
    causes.append(Cmd("all", "Enable timer to recover from all error causes", handler=cause))
    return Cmd("errdisable", "Error disable", children=[
        Cmd("recovery", "Error disable recovery", children=[
            Cmd("cause", "Enable error disable recovery for application", children=causes),
            Cmd("interval", "Error disable recovery timer value",
                args_hint="" if negate else "<30-86400>", handler=interval),
        ]),
    ])


def _mac_table_tree(negate: bool) -> "Cmd":
    """``[no] mac address-table static ... / aging-time <0|10-1000000>``."""
    return Cmd("mac", "Global MAC configuration subcommands", children=[
        Cmd("address-table", "Configure the MAC address table", children=[
            Cmd("static", "static keyword",
                args_hint="<H.H.H> vlan <1-4094> interface <interface>",
                handler=lambda s, t: s._cmd_mac_static(t, not negate)),
            Cmd("aging-time", "Set MAC address table entry maximum age",
                args_hint="" if negate else "<0|10-1000000>",
                handler=lambda s, t: s._cmd_mac_aging(t, negate)),
        ]),
    ])


def _port_security_tree(negate: bool) -> "Cmd":
    """``[no] switchport port-security ...`` on an interface."""
    run = lambda s, t: s._cmd_port_security(t, negate)  # noqa: E731
    neg = run if negate else None      # "no" forms may stop before the value

    def mac_arg() -> "Cmd":
        return Cmd("H.H.H", "48 bit mac address",
                   arg=lambda t: _parse_mac(t) is not None, handler=run)

    return Cmd("port-security", "Security related command", handler=run, children=[
        Cmd("aging", "Port-security aging commands", children=[
            Cmd("time", "Port-security aging time", handler=neg, children=[
                Cmd("<1-1440>", "Aging time in minutes. Enter a value between 1 and 1440",
                    arg=_int_in(1, 1440), handler=run)]),
            Cmd("type", "Port-security aging type", handler=neg, children=[
                Cmd("absolute", "Absolute aging (default)", handler=run),
                Cmd("inactivity", "Aging based on inactivity time period", handler=run)]),
        ]),
        Cmd("mac-address", "Secure mac address", children=[
            Cmd("sticky", "Configure dynamic secure addresses as sticky", handler=run,
                children=[mac_arg()]),
            mac_arg(),
        ]),
        Cmd("maximum", "Max secure addresses", handler=neg, children=[
            Cmd("<1-132>", "Maximum addresses", arg=_int_in(1, 132), handler=run)]),
        Cmd("violation", "Security violation mode", handler=neg, children=[
            Cmd("protect", "Security violation protect mode", handler=run),
            Cmd("restrict", "Security violation restrict mode", handler=run),
            Cmd("shutdown", "Security violation shutdown mode", handler=run),
        ]),
    ])


class SwitchingCommands:
    """MAC address table, err-disable and port security. (mixed into ``CLISession``)."""

    def _cmd_clear_mac(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return _invalid_at(" ".join(tokens[:2]), tokens[1])
        # tokens: clear mac address-table [dynamic] [address M | interface I | vlan N]
        args = tokens[3:]
        if args and "dynamic".startswith(args[0].lower()):
            args = args[1:]
        if not args:
            switch.clear_dynamic_mac_addresses()
            return ""
        key = args[0].lower()
        if len(args) < 2:
            return "% Incomplete command."
        if "address".startswith(key):
            mac = _parse_mac(args[1])
            if mac is None:
                return _invalid_at(" ".join(tokens), args[1])
            switch.clear_dynamic_mac_addresses(address=mac)
        elif "interface".startswith(key):
            device = self.simulation.topology.devices[self.device_id]
            joined = _join_iface_tokens(args, 1)
            found = _match_iface(joined[1], list(device.interfaces))
            if len(found) != 1:
                return _invalid_at(" ".join(tokens), args[1])
            switch.clear_dynamic_mac_addresses(interface=found[0])
        elif "vlan".startswith(key) and args[1].isdigit():
            switch.clear_dynamic_mac_addresses(vlan=int(args[1]))
        else:
            return _invalid_at(" ".join(tokens), args[0])
        return ""

    def _cmd_port_security(self, tokens: list[str], negate: bool) -> str:
        """[no] switchport port-security [maximum|violation|mac-address|aging ...]"""
        from simulator_core.l2.port_security import (
            SECURE_CONFIGURED, SECURE_DYNAMIC, SECURE_STICKY, SecureAddress,
        )
        err = self._require_physical_switchport()
        if err:
            return err
        switch = self._get_switch()
        iface = self._get_current_iface()
        if switch is None or iface is None:
            return "% port-security is only available on switch ports."
        name = self.current_iface
        words = tokens[tokens.index(next(t for t in tokens
                                         if "port-security".startswith(t.lower())
                                         and t.lower().startswith("port"))) + 1:]
        if not negate and iface.switchport_mode.startswith("dynamic_"):
            return f"Command rejected: {_long_name(name)} is a dynamic port."
        ps = switch.port_security(name)

        def kw(word: str, options: list[str]) -> str:
            found = _match(word, options)
            return found[0] if len(found) == 1 else word.lower()

        if not words:                                       # enable / disable
            ps.enabled = not negate
            if negate:
                ps.remove_kind(SECURE_DYNAMIC)
            return ""
        first = kw(words[0], ["aging", "mac-address", "maximum", "violation"])
        rest = words[1:]
        if first == "maximum":
            ps.maximum = 1 if negate or not rest else int(rest[0])
        elif first == "violation":
            ps.violation = "shutdown" if negate or not rest else \
                kw(rest[0], ["protect", "restrict", "shutdown"])
        elif first == "aging":
            what = kw(rest[0], ["time", "type"]) if rest else ""
            if what == "time":
                ps.aging_time = 0 if negate or len(rest) < 2 else int(rest[1])
            elif what == "type":
                ps.aging_type = "absolute" if negate or len(rest) < 2 else \
                    kw(rest[1], ["absolute", "inactivity"])
        elif first == "mac-address":
            sticky = bool(rest) and kw(rest[0], ["sticky"]) == "sticky" and _parse_mac(rest[0]) is None
            mac_text = (rest[1] if sticky and len(rest) > 1 else
                        None if sticky else rest[0] if rest else None)
            if mac_text is None:                            # [no] ... mac-address sticky
                if negate:
                    ps.sticky = False
                    ps.convert(SECURE_STICKY, SECURE_DYNAMIC)
                else:
                    ps.sticky = True
                    ps.convert(SECURE_DYNAMIC, SECURE_STICKY)
                return ""
            mac = _parse_mac(mac_text)
            vlan = switch._psec_vlan(name)
            key = (mac, vlan)
            if negate:
                ps.addresses.pop(key, None)
                return ""
            if key not in ps.addresses:
                if switch.secure_address_owner(mac, vlan, exclude=name) is not None:
                    return f"Found duplicate mac-address {_cisco_mac(mac)}."
                if len(ps.addresses) >= ps.maximum:
                    return (f"Total secure mac-addresses on interface {_long_name(name)} "
                            f"has reached maximum limit.")
            now = self.simulation.lab_time
            ps.addresses[key] = SecureAddress(
                kind=SECURE_STICKY if sticky else SECURE_CONFIGURED,
                learned_at=now, last_seen=now)
        return ""

    def _cmd_show_port_security(self, tokens: list[str]) -> str:
        """show port-security [interface <name> | address]"""
        from simulator_core.l2.port_security import SYSTEM_ADDRESS_LIMIT
        switch = self._get_switch()
        if switch is None:
            return "% show port-security is only available on switch devices."
        device = self.simulation.topology.devices[self.device_id]
        args = tokens[2:]
        secure = switch.secure_ports()
        extra = sum(max(0, len(ps.addresses) - 1) for ps in secure.values())
        footer = [
            f"Total Addresses in System (excluding one mac per port)     : {extra}",
            f"Max Addresses limit in System (excluding one mac per port) : {SYSTEM_ADDRESS_LIMIT}",
        ]
        if args and "interface".startswith(args[0].lower()):
            joined = _join_iface_tokens(args, 1)
            if len(joined) < 2:
                return "% Incomplete command."
            found = _match_iface(joined[1], list(device.interfaces))
            if len(found) != 1:
                return _invalid_at(" ".join(tokens), args[1])
            return self._port_security_detail(switch, found[0])
        if args and "address".startswith(args[0].lower()):
            lines = [
                "               Secure Mac Address Table",
                "-" * 77,
                "Vlan    Mac Address       Type                          Ports   Remaining Age",
                "                                                                   (mins)    ",
                "----    -----------       ----                          -----   -------------",
            ]
            now = self.simulation.lab_time
            for port in sorted(secure, key=_natural_key):
                ps = secure[port]
                for (mac, vlan), a in sorted(ps.addresses.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                    age = "-"
                    if ps.aging_time and a.kind == "SecureDynamic":
                        since = a.learned_at if ps.aging_type == "absolute" else a.last_seen
                        age = str(max(0, int((ps.aging_time * 60 - (now - since)) // 60)))
                    lines.append(f"{vlan:>4}    {_cisco_mac(mac)}    {a.kind:<30}{port:<8}{age:>6}")
            return "\n".join(lines + ["-" * 77] + footer)
        if args:
            return _invalid_at(" ".join(tokens[:3]), args[0])
        lines = [
            "Secure Port  MaxSecureAddr  CurrentAddr  SecurityViolation  Security Action",
            "                (Count)       (Count)          (Count)",
            "-" * 75,
        ]
        for port in sorted(secure, key=_natural_key):
            ps = secure[port]
            lines.append(f"{port:>11}{ps.maximum:>15}{len(ps.addresses):>13}"
                         f"{ps.violation_count:>19}{ps.violation.capitalize():>17}")
        return "\n".join(lines + ["-" * 75] + footer)

    def _port_security_detail(self, switch, port: str) -> str:
        from simulator_core.types import InterfaceState
        iface = self.simulation.topology.devices[self.device_id].interfaces[port]
        ps = switch.port_security_config(port)
        enabled = bool(ps and ps.enabled)
        if not enabled:
            status = "Secure-down"
        elif iface.err_disabled == "psecure-violation":
            status = "Secure-shutdown"
        elif iface.oper_state == InterfaceState.UP:
            status = "Secure-up"
        else:
            status = "Secure-down"
        if ps is None:
            from simulator_core.l2.port_security import PortSecurity
            ps = PortSecurity()
        last = (f"{_cisco_mac(ps.last_source[0])}:{ps.last_source[1]}"
                if ps.last_source else "0000.0000.0000:0")
        return "\n".join([
            f"Port Security              : {'Enabled' if enabled else 'Disabled'}",
            f"Port Status                : {status}",
            f"Violation Mode             : {ps.violation.capitalize()}",
            f"Aging Time                 : {ps.aging_time} mins",
            f"Aging Type                 : {ps.aging_type.capitalize()}",
            "SecureStatic Address Aging : Disabled",
            f"Maximum MAC Addresses      : {ps.maximum}",
            f"Total MAC Addresses        : {len(ps.addresses)}",
            f"Configured MAC Addresses   : {ps.count('SecureConfigured')}",
            f"Sticky MAC Addresses       : {ps.count('SecureSticky')}",
            f"Last Source Address:Vlan   : {last}",
            f"Security Violation Count   : {ps.violation_count}",
        ])

    def _cmd_clear_port_security(self, tokens: list[str]) -> str:
        """clear port-security {all|configured|dynamic|sticky} [address M | interface I]"""
        from simulator_core.l2.port_security import SECURE_CONFIGURED, SECURE_DYNAMIC, SECURE_STICKY
        switch = self._get_switch()
        if switch is None:
            return _invalid_at(" ".join(tokens[:2]), tokens[1])
        args = tokens[2:]
        if not args:
            return "% Incomplete command."
        kinds = {"all": {SECURE_CONFIGURED, SECURE_DYNAMIC, SECURE_STICKY},
                 "configured": {SECURE_CONFIGURED}, "dynamic": {SECURE_DYNAMIC},
                 "sticky": {SECURE_STICKY}}
        found = _match(args[0], list(kinds))
        if len(found) != 1:
            return _invalid_at(" ".join(tokens[:3]), args[0])
        port = mac = None
        if len(args) > 1:
            key = args[1].lower()
            if len(args) < 3:
                return "% Incomplete command."
            if "address".startswith(key):
                mac = _parse_mac(args[2])
                if mac is None:
                    return _invalid_at(" ".join(tokens), args[2])
            elif "interface".startswith(key):
                device = self.simulation.topology.devices[self.device_id]
                joined = _join_iface_tokens(args[1:], 1)
                hit = _match_iface(joined[1], list(device.interfaces))
                if len(hit) != 1:
                    return _invalid_at(" ".join(tokens), args[2])
                port = hit[0]
            else:
                return _invalid_at(" ".join(tokens[:4]), args[1])
        switch.clear_port_security(kinds[found[0]], port=port, mac=mac)
        return ""

    def _cmd_errdisable_cause(self, tokens: list[str], enabled: bool) -> str:
        """[no] errdisable recovery cause <cause>|all"""
        switch = self._get_switch()
        if switch is None:
            return "% errdisable recovery is only available on switch devices."
        offset = 1 if tokens[0].lower() == "no" else 0
        word = tokens[3 + offset].lower()
        names = [n for n, _ in _ERRDISABLE_CAUSES]
        found = _match(word, names + ["all"])
        chosen = names if found == ["all"] else found[:1]
        for name in chosen:
            if enabled:
                switch.errdisable_recovery.add(name)
            else:
                switch.errdisable_recovery.discard(name)
        return ""

    def _cmd_errdisable_interval(self, tokens: list[str], negate: bool) -> str:
        """[no] errdisable recovery interval <30-86400>"""
        switch = self._get_switch()
        if switch is None:
            return "% errdisable recovery is only available on switch devices."
        if negate:
            switch.errdisable_interval = 300
            return ""
        if len(tokens) < 4:
            return "% Incomplete command."
        if not tokens[3].isdigit() or not 30 <= int(tokens[3]) <= 86400:
            return _invalid_at(" ".join(tokens[:4]), tokens[3])
        switch.errdisable_interval = int(tokens[3])
        return ""

    def _cmd_show_errdisable_recovery(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show errdisable is only available on switch devices."
        lines = ["ErrDisable Reason            Timer Status",
                 "-----------------            --------------"]
        for name, _ in _ERRDISABLE_CAUSES:
            status = "Enabled" if name in switch.errdisable_recovery else "Disabled"
            lines.append(f"{name:<29}{status}")
        lines += ["", f"Timer interval: {switch.errdisable_interval} seconds", "",
                  "Interfaces that will be enabled at the next timeout:", ""]
        due = []
        device = self.simulation.topology.devices[self.device_id]
        for name in _display_order(device):
            iface = device.interfaces[name]
            if iface.err_disabled and iface.err_disabled in switch.errdisable_recovery:
                left = switch.errdisable_interval - (self.simulation.lab_time - iface.err_disabled_at)
                due.append(f"{name:<16}{iface.err_disabled:>17}{max(0, int(left)):>17}")
        if due:
            lines += ["Interface       Errdisable reason       Time left(sec)",
                      "---------       -----------------       --------------"] + due
        return "\n".join(lines)

    def _cmd_show_errdisable_detect(self, tokens: list[str]) -> str:
        if self._get_switch() is None:
            return "% show errdisable is only available on switch devices."
        lines = ["ErrDisable Reason            Detection    Mode",
                 "-----------------            ---------    ----"]
        lines += [f"{name:<29}{'Enabled':<13}port" for name, _ in _ERRDISABLE_CAUSES]
        return "\n".join(lines)

    def _cmd_mac_static(self, tokens: list[str], add: bool) -> str:
        """
        [no] mac address-table static <H.H.H> vlan <1-4094> interface <name>
        """
        switch = self._get_switch()
        if switch is None:
            return "% mac address-table is only available on switch devices."
        args = tokens[4:] if tokens[0].lower() == "no" else tokens[3:]
        typed = " ".join(tokens[:len(tokens) - len(args)])
        if not args:
            return "% Incomplete command."
        mac = _parse_mac(args[0])
        if mac is None:
            return _invalid_at(f"{typed} {args[0]}", args[0])
        if len(args) < 3:
            return "% Incomplete command."
        if not "vlan".startswith(args[1].lower()) or len(args[1]) < 1:
            return _invalid_at(f"{typed} {' '.join(args[:2])}", args[1])
        if not args[2].isdigit() or not 1 <= int(args[2]) <= 4094:
            return _invalid_at(f"{typed} {' '.join(args[:3])}", args[2])
        vlan = int(args[2])
        if int(mac[:2], 16) & 1:
            return "% Only unicast addresses can be configured to be static"
        port = None
        if len(args) > 3:
            if not "interface".startswith(args[3].lower()) or len(args) < 5:
                return "% Incomplete command." if len(args) == 4 else \
                    _invalid_at(f"{typed} {' '.join(args[:4])}", args[3])
            device = self.simulation.topology.devices[self.device_id]
            joined = _join_iface_tokens(args[3:], 1)
            found = _match_iface(joined[1], list(device.interfaces))
            if len(found) != 1 or not device.interfaces[found[0]].is_physical_switchport:
                return _invalid_at(f"{typed} {' '.join(args)}", args[4])
            port = found[0]
        if add:
            if port is None:
                return "% Incomplete command."
            switch.add_static_mac(mac, vlan, port)
        else:
            switch.remove_static_mac(mac, vlan, port)
        return ""

    def _cmd_mac_aging(self, tokens: list[str], negate: bool) -> str:
        """[no] mac address-table aging-time <0|10-1000000>"""
        switch = self._get_switch()
        if switch is None:
            return "% mac address-table is only available on switch devices."
        if negate:
            switch.mac_aging_time = 300
            return ""
        if len(tokens) < 4:
            return "% Incomplete command."
        value = tokens[3]
        if not value.isdigit() or not (int(value) == 0 or 10 <= int(value) <= 1_000_000):
            return _invalid_at(" ".join(tokens[:4]), value)
        switch.mac_aging_time = int(value)
        return ""

    def _cmd_show_mac(self, tokens: list[str]) -> str:
        """
        show mac address-table [dynamic | static] [address <mac> |
                                interface <name> | vlan <id>]
        show mac address-table count | aging-time
        """
        try:
            switch = self.simulation.get_switch(self.device_id)
        except KeyError:
            return "% show mac address-table is only supported on switch devices."
        device = self.simulation.topology.devices[self.device_id]
        entries = sorted(switch.mac_entries(),
                         key=lambda e: (e[0], _natural_key(e[3]), e[1]))
        args = tokens[3:]
        if args and "aging-time".startswith(args[0].lower()) and args[0].lower().startswith("ag"):
            return "\n".join([f"Global Aging Time: {switch.mac_aging_time:>4}",
                              "Vlan    Aging Time", "----    ----------"])
        if args and "count".startswith(args[0].lower()) and args[0].lower().startswith("c"):
            out = []
            for vlan in sorted({e[0] for e in entries} | set(switch.vlans)):
                rows = [e for e in entries if e[0] == vlan]
                dyn = sum(1 for e in rows if e[2] == "DYNAMIC")
                out += [f"Mac Entries for Vlan {vlan}:", "---------------------------",
                        f"Dynamic Address Count  : {dyn}",
                        f"Static  Address Count  : {len(rows) - dyn}",
                        f"Total Mac Addresses    : {len(rows)}", ""]
            out.append(f"Total Mac Address Space Available: {8128 - len(entries)}")
            return "\n".join(out)
        i = 0
        while i < len(args):
            word = args[i].lower()
            if "dynamic".startswith(word) and word.startswith("d"):
                entries = [e for e in entries if e[2] == "DYNAMIC"]
                i += 1
            elif "static".startswith(word) and word.startswith("s"):
                entries = [e for e in entries if e[2] == "STATIC"]
                i += 1
            elif "address".startswith(word) and word.startswith("ad") and i + 1 < len(args):
                mac = _parse_mac(args[i + 1])
                if mac is None:
                    return _invalid_at(" ".join(tokens[:4 + i + 1]), args[i + 1])
                entries = [e for e in entries if e[1] == mac]
                i += 2
            elif "vlan".startswith(word) and i + 1 < len(args) and args[i + 1].isdigit():
                entries = [e for e in entries if e[0] == int(args[i + 1])]
                i += 2
            elif "interface".startswith(word) and i + 1 < len(args):
                joined = _join_iface_tokens(args[i:], 1)
                found = _match_iface(joined[1], list(device.interfaces))
                if len(found) != 1:
                    return _invalid_at(" ".join(tokens[:4 + i + 1]), args[i + 1])
                entries = [e for e in entries if e[3] == found[0]]
                # "interface Fa0/1" is two tokens, "interface FastEthernet 0/1" three.
                i += 2 + (len(args[i:]) - len(joined))
            else:
                return _invalid_at(" ".join(tokens[:4 + i]), args[i])
        lines = [
            "          Mac Address Table",
            "-------------------------------------------",
            "",
            "Vlan    Mac Address       Type        Ports",
            "----    -----------       --------    -----",
        ]
        for vlan, mac, kind, port in entries:
            lines.append(f"{vlan:>4}    {_cisco_mac(mac)}    {kind:<8}    {port}")
        lines.append(f"Total Mac Addresses for this criterion: {len(entries)}")
        return "\n".join(lines)
