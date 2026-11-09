"""
simulator_core.cli
~~~~~~~~~~~~~~~~~~
Educational Cisco-style CLI for the NetLab Academy simulator.

Design:
- Command tree with prefix expansion (abbreviation) exactly as Cisco IOS.
- `?`  at any point lists completions with descriptions.
- Tab  completes the current token if unambiguous, returns the completed
  line; if ambiguous returns the partial line unchanged (IOS behaviour).
- Ambiguous abbreviations produce "% Ambiguous command: ..." like IOS.
- Per-interface show commands:
    show interfaces <iface>
    show running-config interface <iface>
- `show interfaces` shows ALL interfaces when no name is given.
- Full mode stack: USER_EXEC → PRIV_EXEC → GLOBAL_CONFIG → IFACE_CONFIG.
- No eval, no shell, no subprocess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from ipaddress import IPv4Address, IPv4Network
from typing import TYPE_CHECKING, Callable, Optional

from simulator_core.exceptions import UnsupportedCommandError

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


# ---------------------------------------------------------------------------
# Command tree infrastructure
# ---------------------------------------------------------------------------

@dataclass
class Cmd:
    """
    One node in the command trie.

    *keyword*  — the full keyword for this level (e.g. "show", "ip").
    *help_str* — short description shown in ? output.
    *children* — sub-commands at the next level.
    *handler*  — callable(tokens, session) → str when this is a leaf.
    *args_hint*— shown after this node in ? output (e.g. "<ip-address>").
    """
    keyword: str
    help_str: str = ""
    children: list["Cmd"] = field(default_factory=list)
    handler: Optional[Callable[["CLISession", list[str]], str]] = None
    args_hint: str = ""

    def child(self, keyword: str) -> Optional["Cmd"]:
        """Return the child with the given keyword, or None."""
        for c in self.children:
            if c.keyword == keyword:
                return c
        return None


def _match(token: str, keywords: list[str]) -> list[str]:
    """
    Return all keywords that *token* is a valid prefix of.
    Exact match wins: if token == one keyword exactly, return just that one.
    """
    exact = [k for k in keywords if k == token]
    if exact:
        return exact
    return [k for k in keywords if k.startswith(token)]


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

class CLIMode(Enum):
    USER_EXEC     = auto()
    PRIV_EXEC     = auto()
    GLOBAL_CONFIG = auto()
    IFACE_CONFIG  = auto()
    VLAN_CONFIG   = auto()


# ---------------------------------------------------------------------------
# CLISession
# ---------------------------------------------------------------------------

@dataclass
class CLISession:
    """
    Active terminal session on one simulated device.
    One session per open terminal window.
    """
    device_id: str
    simulation: "Simulation"
    mode: CLIMode = CLIMode.USER_EXEC
    current_iface: Optional[str] = None
    current_vlan: Optional[int] = None  # VLAN ID when in VLAN_CONFIG

    # ── Public API ────────────────────────────────────────────────────────────

    def prompt(self) -> str:
        device = self.simulation.topology.devices.get(self.device_id)
        hostname = device.hostname if device else self.device_id
        suffixes = {
            CLIMode.USER_EXEC:     ">",
            CLIMode.PRIV_EXEC:     "#",
            CLIMode.GLOBAL_CONFIG: "(config)#",
            CLIMode.IFACE_CONFIG:  "(config-if)#",
            CLIMode.VLAN_CONFIG:   "(config-vlan)#",
        }
        return f"{hostname}{suffixes.get(self.mode, '>')}"

    def execute(self, raw: str) -> str:
        """
        Parse and execute a command line.

        Returns the output string.  Never raises — unknown input returns
        the standard Cisco invalid-input error.
        """
        line = raw.rstrip()
        stripped = line.strip()

        # Ctrl+Z is identical to 'end'
        if stripped == "\x1a" or stripped.lower() == "end":
            return self._cmd_end([])

        if not stripped:
            return ""

        # Inline ?-help (can appear anywhere on the line)
        if stripped.endswith("?"):
            return self._inline_help(stripped)

        tokens = stripped.split()

        # exit/end are universal
        if tokens[0].lower() in ("exit", "end", "quit"):
            return self._cmd_end(tokens)

        tree = self._tree()
        return self._dispatch(tokens, tree)

    def complete(self, partial: str) -> str:
        """
        Tab-complete *partial*.

        Returns the completed line if exactly one match exists,
        or the original line unchanged if zero or multiple matches.
        Mirrors Cisco IOS tab behaviour.
        """
        if not partial.strip():
            return partial

        tokens = partial.rstrip().split()
        # If line ends with a space, user is starting a new token
        ends_with_space = partial.endswith(" ")

        tree = self._tree()
        node_list = tree
        completed_tokens: list[str] = []

        # Walk as far as we can with full matches
        for i, tok in enumerate(tokens):
            is_last = (i == len(tokens) - 1) and not ends_with_space
            keywords = [c.keyword for c in node_list]
            matches = _match(tok, keywords)

            if is_last:
                if len(matches) == 1:
                    completed_tokens.append(matches[0])
                    return " ".join(completed_tokens)
                else:
                    # Zero or ambiguous — return unchanged
                    completed_tokens.append(tok)
                    return " ".join(completed_tokens)
            else:
                if len(matches) == 1:
                    completed_tokens.append(matches[0])
                    child = next(c for c in node_list if c.keyword == matches[0])
                    node_list = child.children
                elif len(matches) == 0:
                    # No match — return unchanged
                    return partial.rstrip()
                else:
                    completed_tokens.append(tok)
                    return " ".join(completed_tokens)

        return partial.rstrip()

    # ── Command tree per mode ─────────────────────────────────────────────────

    def _tree(self) -> list[Cmd]:
        """Return the command list for the current mode."""
        if self.mode == CLIMode.USER_EXEC:
            return self._user_tree()
        if self.mode == CLIMode.PRIV_EXEC:
            return self._priv_tree()
        if self.mode == CLIMode.GLOBAL_CONFIG:
            return self._global_tree()
        if self.mode == CLIMode.IFACE_CONFIG:
            return self._iface_tree()
        if self.mode == CLIMode.VLAN_CONFIG:
            return self._vlan_tree()
        return []

    def _user_tree(self) -> list[Cmd]:
        return [
            Cmd("enable",    "Enter privileged EXEC mode",
                handler=lambda s, t: s._cmd_enable(t)),
            Cmd("ping",      "Send ICMP echo messages",
                args_hint="<ip-address> [repeat <n>]",
                handler=lambda s, t: s._cmd_ping(t)),
            Cmd("traceroute","Trace route to destination (not yet supported)",
                handler=lambda s, t: "% traceroute: not yet supported in this simulator."),
            Cmd("show",      "Show running system information",
                children=self._show_subcmds(), handler=None),
            Cmd("exit",      "Exit current mode",
                handler=lambda s, t: s._cmd_end(t)),
        ]

    def _priv_tree(self) -> list[Cmd]:
        return [
            Cmd("configure", "Enter configuration mode",
                children=[
                    Cmd("terminal", "Enter global configuration mode",
                        handler=lambda s, t: s._cmd_conf_terminal(t)),
                ]),
            Cmd("disable",   "Exit privileged EXEC mode",
                handler=lambda s, t: s._cmd_disable(t)),
            Cmd("ping",      "Send ICMP echo messages",
                args_hint="<ip-address> [repeat <n>]",
                handler=lambda s, t: s._cmd_ping(t)),
            Cmd("traceroute","Trace route (not yet supported)",
                handler=lambda s, t: "% traceroute: not yet supported."),
            Cmd("show",      "Show running system information",
                children=self._show_subcmds(), handler=None),
            Cmd("debug",     "Debugging functions (not supported)",
                handler=lambda s, t: "% debug: not supported in this simulator."),
            Cmd("undebug",   "Disable debugging",
                handler=lambda s, t: "% undebug: not supported in this simulator."),
            Cmd("reload",    "Halt and perform a cold restart",
                handler=lambda s, t: "% reload: not supported in simulation."),
            Cmd("write",     "Write running configuration to memory",
                children=[
                    Cmd("memory", "Write to NV memory",
                        handler=lambda s, t: "Building configuration...\n[OK]"),
                    Cmd("terminal","Write to terminal",
                        handler=lambda s, t: s._cmd_show_running(t)),
                ], handler=None),
            Cmd("copy",      "Copy from one file to another",
                handler=lambda s, t: "% copy: not supported in this simulator."),
            Cmd("clear",     "Reset functions",
                children=[
                    Cmd("arp",  "Delete entries from the ARP table",
                        handler=lambda s, t: ""),
                ]),
            Cmd("exit",      "Exit current mode",
                handler=lambda s, t: s._cmd_end(t)),
            Cmd("end",       "End and return to privileged EXEC",
                handler=lambda s, t: s._cmd_end(t)),
        ]

    def _global_tree(self) -> list[Cmd]:
        return [
            Cmd("hostname",   "Set system's network name",
                args_hint="<hostname>",
                handler=lambda s, t: s._cmd_hostname(t)),
            Cmd("interface",  "Select an interface to configure",
                args_hint="<interface-name>",
                handler=lambda s, t: s._cmd_enter_iface(t)),
            Cmd("vlan",       "Configure a VLAN",
                args_hint="<vlan-id>",
                handler=lambda s, t: s._cmd_enter_vlan(t)),
            Cmd("no",         "Negate a command or set its defaults",
                children=[
                    Cmd("vlan", "Delete a VLAN",
                        args_hint="<vlan-id>",
                        handler=lambda s, t: s._cmd_no_vlan(t)),
                    Cmd("hostname", "Reset hostname",
                        handler=lambda s, t: s._cmd_hostname(["hostname", "Router"])),
                ]),
            Cmd("ip",         "IP configuration",
                children=[
                    Cmd("routing", "Enable IP routing (no effect in L2-only sim)",
                        handler=lambda s, t: ""),
                ]),
            Cmd("banner",     "Define a login banner (not persisted)",
                handler=lambda s, t: ""),
            Cmd("do",         "Run an EXEC command from config mode",
                args_hint="<exec-command>",
                handler=lambda s, t: s._cmd_do(t)),
            Cmd("exit",       "Exit from current mode",
                handler=lambda s, t: s._cmd_end(t)),
            Cmd("end",        "End and return to privileged EXEC",
                handler=lambda s, t: s._cmd_end(t)),
        ]

    def _iface_tree(self) -> list[Cmd]:
        return [
            Cmd("ip",          "Interface IP commands",
                children=[
                    Cmd("address",   "Set the IP address of an interface",
                        args_hint="<ip-address> <subnet-mask>",
                        handler=lambda s, t: s._cmd_ip_address(t)),
                ]),
            Cmd("no",          "Negate or reset to default",
                children=[
                    Cmd("ip",        "Remove IP configuration",
                        children=[
                            Cmd("address", "Remove IP address",
                                handler=lambda s, t: s._cmd_no_ip_address(t)),
                        ]),
                    Cmd("shutdown",  "Enable interface",
                        handler=lambda s, t: s._cmd_no_shutdown(t)),
                    Cmd("description","Remove description",
                        handler=lambda s, t: s._cmd_no_description(t)),
                    Cmd("switchport", "Reset switchport to default VLAN",
                        handler=lambda s, t: s._cmd_no_switchport(t)),
                ]),
            Cmd("shutdown",    "Shutdown the selected interface",
                handler=lambda s, t: s._cmd_shutdown(t)),
            Cmd("description", "Interface specific description",
                args_hint="<description-text>",
                handler=lambda s, t: s._cmd_description(t)),
            Cmd("switchport",  "Switch port configuration",
                children=[
                    Cmd("mode",   "Set interface mode",
                        children=[
                            Cmd("access", "Set access mode",
                                handler=lambda s, t: s._cmd_switchport_mode_access(t)),
                            Cmd("trunk",  "Set trunk mode (not yet supported)",
                                handler=lambda s, t: "% Trunk mode is not yet supported."),
                        ]),
                    Cmd("access", "Set access VLAN",
                        args_hint="vlan <vlan-id>",
                        children=[
                            Cmd("vlan", "Assign access VLAN",
                                args_hint="<vlan-id>",
                                handler=lambda s, t: s._cmd_switchport_access_vlan(t)),
                        ]),
                ]),
            Cmd("duplex",      "Configure duplex operation (no effect in sim)",
                handler=lambda s, t: ""),
            Cmd("speed",       "Configure interface speed (no effect in sim)",
                handler=lambda s, t: ""),
            Cmd("do",          "Run an EXEC command from config mode",
                args_hint="<exec-command>",
                handler=lambda s, t: s._cmd_do(t)),
            Cmd("exit",        "Exit from interface configuration mode",
                handler=lambda s, t: s._cmd_end(t)),
            Cmd("end",         "End and return to privileged EXEC",
                handler=lambda s, t: s._cmd_end(t)),
        ]

    def _vlan_tree(self) -> list[Cmd]:
        return [
            Cmd("name",    "Set the VLAN name",
                args_hint="<vlan-name>",
                handler=lambda s, t: s._cmd_vlan_name(t)),
            Cmd("no",      "Negate a command",
                children=[
                    Cmd("name", "Reset VLAN name to default",
                        handler=lambda s, t: s._cmd_no_vlan_name(t)),
                ]),
            Cmd("do",      "Run an EXEC command from config mode",
                args_hint="<exec-command>",
                handler=lambda s, t: s._cmd_do(t)),
            Cmd("exit",    "Exit from VLAN configuration mode",
                handler=lambda s, t: s._cmd_end(t)),
            Cmd("end",     "End and return to privileged EXEC",
                handler=lambda s, t: s._cmd_end(t)),
        ]

    def _show_subcmds(self) -> list[Cmd]:
        return [
            Cmd("version",     "System hardware and software status",
                handler=lambda s, t: s._cmd_show_version(t)),
            Cmd("ip",          "IP information",
                children=[
                    Cmd("interface", "IP interface status and configuration",
                        children=[
                            Cmd("brief", "Brief summary of IP status",
                                handler=lambda s, t: s._cmd_show_ip_int_brief(t)),
                        ] + [
                            Cmd(name, f"Interface {name}",
                                handler=lambda s, t, n=name: s._cmd_show_ip_iface(t, n))
                            for name in self._iface_names()
                        ]),
                    Cmd("route",     "IP routing table",
                        handler=lambda s, t: s._cmd_show_ip_route(t)),
                    Cmd("arp",       "IP ARP table",
                        handler=lambda s, t: s._cmd_show_arp(t)),
                ]),
            Cmd("interfaces",  "Interface status and configuration",
                children=[
                    Cmd("brief", "Brief summary of interface status (alias)",
                        handler=lambda s, t: s._cmd_show_ip_int_brief(t)),
                ] + [
                    Cmd(name, f"Interface {name}",
                        handler=lambda s, t, n=name: s._cmd_show_interface(t, n))
                    for name in self._iface_names()
                ],
                handler=lambda s, t: s._cmd_show_interfaces_all(t)),
            Cmd("arp",         "ARP table",
                handler=lambda s, t: s._cmd_show_arp(t)),
            Cmd("mac",         "MAC forwarding table commands",
                children=[
                    Cmd("address-table", "MAC address forwarding table",
                        handler=lambda s, t: s._cmd_show_mac(t)),
                ]),
            Cmd("running-config", "Current operating configuration",
                children=[
                    Cmd("interface", "Interface configuration",
                        children=[
                            Cmd(name, f"Interface {name}",
                                handler=lambda s, t, n=name: s._cmd_show_running_iface(t, n))
                            for name in self._iface_names()
                        ]),
                ],
                handler=lambda s, t: s._cmd_show_running(t)),
            Cmd("startup-config", "Contents of startup configuration",
                handler=lambda s, t: "% startup-config is not supported in this simulator."),
            Cmd("vlan",        "VTP VLAN status",
                children=[
                    Cmd("brief", "VTP management domain status and one line for each VLAN",
                        handler=lambda s, t: s._cmd_show_vlan_brief(t)),
                ],
                handler=lambda s, t: s._cmd_show_vlan_brief(t)),
            Cmd("cdp",         "CDP information (not simulated)",
                handler=lambda s, t: "% CDP is not supported in this simulator."),
            Cmd("clock",       "Display the system clock",
                handler=lambda s, t: f"% Logical clock: tick {self.simulation.clock}"),
            Cmd("history",     "Display the session command history",
                handler=lambda s, t: "% Command history: not yet implemented."),
        ]

    def _iface_names(self) -> list[str]:
        """Return sorted interface names for the current device."""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return []
        return sorted(device.interfaces.keys())

    # ── Dispatch engine ───────────────────────────────────────────────────────

    def _dispatch(self, tokens: list[str], tree: list[Cmd]) -> str:
        """
        Walk the command tree matching tokens with prefix expansion.
        Returns the handler output or an error string.
        """
        node_list = tree
        matched_path: list[str] = []

        for depth, tok in enumerate(tokens):
            keywords = [c.keyword for c in node_list]
            matches = _match(tok.lower(), keywords)

            if len(matches) == 0:
                if depth == 0:
                    return _invalid(tok)
                # Unknown sub-command after a valid prefix
                bad = " ".join(tokens[:depth] + [tok])
                return _invalid_at(bad, tok)

            if len(matches) > 1:
                return _ambiguous(tok, matches)

            keyword = matches[0]
            matched_path.append(keyword)
            cmd_node = next(c for c in node_list if c.keyword == keyword)

            remaining = tokens[depth + 1:]

            # If this node has a handler and no children (leaf), run it.
            if cmd_node.handler and not cmd_node.children:
                return cmd_node.handler(self, tokens)

            # If this node has a handler AND children, check remaining tokens.
            if cmd_node.handler and cmd_node.children:
                if not remaining:
                    # No more tokens — run the handler.
                    return cmd_node.handler(self, tokens)
                # There are more tokens — try children first.
                node_list = cmd_node.children
                continue

            # Node has only children (no handler).
            if not cmd_node.children:
                # Dead end with no handler
                return _invalid(" ".join(tokens))

            if not remaining:
                # Stopped mid-tree with no handler
                return f"% Incomplete command."

            node_list = cmd_node.children

        # Fell off the end of tokens mid-tree
        return "% Incomplete command."

    # ── Inline ? help ─────────────────────────────────────────────────────────

    def _inline_help(self, line: str) -> str:
        """
        Generate context-sensitive help for a line ending with '?'.
        Mirrors IOS: 'show ?' lists sub-commands of show.
        """
        # Remove trailing ?
        before = line.rstrip("?").rstrip()
        tokens = before.split() if before else []

        tree = self._tree()
        node_list = tree

        if not tokens:
            # '?' at the start of a blank line
            return _format_help(node_list)

        # Walk tree to find current context
        for depth, tok in enumerate(tokens):
            keywords = [c.keyword for c in node_list]
            matches = _match(tok.lower(), keywords)

            if len(matches) == 0:
                return f"% No help available for {tok!r}"
            if len(matches) > 1:
                return _format_help([c for c in node_list if c.keyword in matches])

            keyword = matches[0]
            cmd_node = next(c for c in node_list if c.keyword == keyword)

            if depth == len(tokens) - 1:
                # Last token — show children of this node
                if cmd_node.children:
                    return _format_help(cmd_node.children)
                if cmd_node.args_hint:
                    return f"  {cmd_node.args_hint:<30} {cmd_node.help_str}"
                return f"  <cr>{'':26} {cmd_node.help_str}"

            node_list = cmd_node.children
            if not node_list:
                return f"  <cr>"

        # Should not reach here
        return _format_help(node_list)

    # ── Command implementations ───────────────────────────────────────────────

    def _cmd_end(self, tokens: list[str]) -> str:
        cmd = tokens[0].lower() if tokens else "exit"

        # `end` (and Ctrl+Z) always jumps to PRIV_EXEC regardless of depth.
        if cmd == "end":
            self.mode = CLIMode.PRIV_EXEC
            self.current_iface = None
            return ""

        # `exit` goes one level back.
        if self.mode == CLIMode.IFACE_CONFIG:
            self.mode = CLIMode.GLOBAL_CONFIG
            self.current_iface = None
        elif self.mode == CLIMode.VLAN_CONFIG:
            self.mode = CLIMode.GLOBAL_CONFIG
            self.current_vlan = None
        elif self.mode == CLIMode.GLOBAL_CONFIG:
            self.mode = CLIMode.PRIV_EXEC
        elif self.mode == CLIMode.PRIV_EXEC:
            self.mode = CLIMode.USER_EXEC
        # USER_EXEC: caller decides (close terminal)
        return ""

    def _cmd_enable(self, tokens: list[str]) -> str:
        self.mode = CLIMode.PRIV_EXEC
        return ""

    def _cmd_disable(self, tokens: list[str]) -> str:
        self.mode = CLIMode.USER_EXEC
        return ""

    def _cmd_conf_terminal(self, tokens: list[str]) -> str:
        self.mode = CLIMode.GLOBAL_CONFIG
        return "Enter configuration commands, one per line.  End with CNTL/Z."

    def _cmd_hostname(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        device = self.simulation.topology.devices.get(self.device_id)
        if device:
            device.hostname = tokens[1]
        return ""

    def _cmd_enter_iface(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        iface_name = tokens[1]
        device = self.simulation.topology.devices.get(self.device_id)
        # Try prefix match on interface names
        iface_names = list(device.interfaces.keys()) if device else []
        matches = [n for n in iface_names if n.lower().startswith(iface_name.lower())]
        if not matches:
            return f"% Invalid interface name: {iface_name!r}"
        if len(matches) > 1:
            exact = [n for n in matches if n.lower() == iface_name.lower()]
            if exact:
                matches = exact
            else:
                return f"% Ambiguous interface: {iface_name!r}\n  Matches: {', '.join(matches)}"
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = matches[0]
        return ""

    def _cmd_do(self, tokens: list[str]) -> str:
        """do <exec-command> — run EXEC command from config mode."""
        if len(tokens) < 2:
            return "% Incomplete command."
        # Run in a temporary PRIV_EXEC context
        saved_mode = self.mode
        saved_iface = self.current_iface
        self.mode = CLIMode.PRIV_EXEC
        result = self._dispatch(tokens[1:], self._tree())
        self.mode = saved_mode
        self.current_iface = saved_iface
        return result

    # ── Interface config commands ──────────────────────────────────────────────

    def _get_current_iface(self):
        device = self.simulation.topology.devices.get(self.device_id)
        return device.interfaces.get(self.current_iface) if device and self.current_iface else None

    def _cmd_ip_address(self, tokens: list[str]) -> str:
        # tokens: ['ip', 'address', '<ip>', '<mask>']
        if len(tokens) < 4:
            return "% Incomplete command.\nUsage: ip address <ip-address> <subnet-mask>"
        ip_str, mask_str = tokens[2], tokens[3]
        try:
            ip = IPv4Address(ip_str)
            # Accept both prefix length (24) and dotted mask (255.255.255.0)
            if "." in mask_str:
                mask_int = int(IPv4Address(mask_str))
                prefix = bin(mask_int).count("1")
            else:
                prefix = int(mask_str)
            if not 0 <= prefix <= 32:
                raise ValueError("prefix out of range")
            cidr = f"{ip}/{prefix}"
        except (ValueError, Exception):
            return f"% Invalid IP address or mask: {ip_str} {mask_str}"
        iface = self._get_current_iface()
        if iface:
            try:
                iface.set_ip(cidr)
            except Exception as exc:
                return f"% {exc}"
        return ""

    def _cmd_no_ip_address(self, tokens: list[str]) -> str:
        iface = self._get_current_iface()
        if iface:
            iface.ip_config = None
        return ""

    def _cmd_shutdown(self, tokens: list[str]) -> str:
        from simulator_core.types import InterfaceState
        iface = self._get_current_iface()
        if iface:
            iface.admin_state = InterfaceState.DOWN
            iface.oper_state  = InterfaceState.DOWN
        return ""

    def _cmd_no_shutdown(self, tokens: list[str]) -> str:
        from simulator_core.types import InterfaceState
        iface = self._get_current_iface()
        if iface:
            iface.admin_state = InterfaceState.UP
            iface.oper_state  = InterfaceState.UP
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

    # ── VLAN config commands ────────────────────────────────────────────────────

    def _get_switch(self):
        """Return the Switch object for this session, or None."""
        try:
            return self.simulation.get_switch(self.device_id)
        except KeyError:
            return None

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

    # ── Switchport commands ───────────────────────────────────────────────────

    def _cmd_switchport_mode_access(self, tokens: list[str]) -> str:
        iface = self._get_current_iface()
        if iface:
            iface.switchport_mode = "access"
        return ""

    def _cmd_switchport_access_vlan(self, tokens: list[str]) -> str:
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
        try:
            switch.set_port_vlan(self.current_iface, vlan_id)
        except ValueError as exc:
            return f"% {exc}"
        return ""

    def _cmd_no_switchport(self, tokens: list[str]) -> str:
        iface = self._get_current_iface()
        if iface:
            iface.vlan = 1
            iface.switchport_mode = "access"
        return ""

    # ── Ping ──────────────────────────────────────────────────────────────────

    def _cmd_ping(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command.\nUsage: ping <ip-address> [repeat <count>]"
        target = tokens[1]
        repeat = 5
        for i, tok in enumerate(tokens):
            if tok.lower() == "repeat" and i + 1 < len(tokens):
                try:
                    repeat = max(1, min(100, int(tokens[i + 1])))
                except ValueError:
                    pass
        try:
            IPv4Address(target)
        except ValueError:
            return f"% Bad IP address or host name -- {target!r}"

        from simulator_core.exceptions import ConfigurationError
        try:
            host = self.simulation.get_host(self.device_id)
        except KeyError:
            return "% Ping is not supported on this device type."
        try:
            result = host.ping(target, count=repeat)
        except ConfigurationError as exc:
            return f"% {exc}"
        self.simulation.run()

        lines = [
            "\nType escape sequence to abort.",
            f"Sending {result.sent}, 100-byte ICMP Echos to {target}, timeout is 2 seconds:",
            "".join("!" if r.success else "." for r in result.results),
        ]
        pct = int(result.received / result.sent * 100) if result.sent else 0
        summary = f"Success rate is {pct} percent ({result.received}/{result.sent})"
        if result.received:
            rtts = [r.rtt_ticks for r in result.results if r.success and r.rtt_ticks is not None]
            if rtts:
                summary += f", round-trip min/avg/max = {min(rtts)}/{sum(rtts)//len(rtts)}/{max(rtts)} ticks"
        lines.append(summary)
        if result.received == 0 and result.results and result.results[0].drop_reason:
            lines.append(f"% {result.results[0].drop_reason}")
        return "\n".join(lines)

    # ── Show commands ─────────────────────────────────────────────────────────

    def _cmd_show_version(self, tokens: list[str]) -> str:
        return (
            "\nNetLab Academy Educational Simulator\n"
            "Version 0.1.0 (simulator-core)\n"
            "Copyright (c) NetLab Academy -- educational use only.\n"
            "This is not Cisco IOS. Supported commands are documented.\n\n"
            f"Uptime: {self.simulation.clock} logical ticks\n"
            "Processor board ID: EDUCATIONAL\n"
        )

    def _cmd_show_ip_int_brief(self, tokens: list[str]) -> str:
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        from simulator_core.types import InterfaceState
        lines = [
            "Interface                  IP-Address      OK? Method Status                Protocol",
        ]
        for name, iface in device.interfaces.items():
            ip     = str(iface.ip_config.address) if iface.ip_config else "unassigned"
            ok     = "YES" if iface.ip_config else "NO "
            method = "manual" if iface.ip_config else "unset "
            status = "up      " if iface.admin_state == InterfaceState.UP else "administratively down"
            proto  = "up    "  if iface.oper_state  == InterfaceState.UP else "down  "
            lines.append(f"{name:<26} {ip:<15} {ok}  {method:<6} {status:<21} {proto}")
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
        up    = iface.admin_state == InterfaceState.UP
        proto = iface.oper_state  == InterfaceState.UP
        lines = [
            f"{iface_name} is {'up' if up else 'administratively down'}, line protocol is {'up' if proto else 'down'}",
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

    def _cmd_show_ip_route(self, tokens: list[str]) -> str:
        return (
            "Codes: C - connected, S - static\n\n"
            "% Routing is not yet implemented in this simulator.\n"
            "  (Stage C — static routing is a planned feature.)"
        )

    def _cmd_show_interfaces_all(self, tokens: list[str]) -> str:
        """show interfaces — all interfaces."""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        blocks = []
        for name in device.interfaces:
            blocks.append(self._iface_block(name))
        return "\n\n".join(blocks)

    def _cmd_show_interface(self, tokens: list[str], iface_name: str) -> str:
        """show interfaces <name>"""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        if iface_name not in device.interfaces:
            return f"% Interface {iface_name!r} not found."
        return self._iface_block(iface_name)

    def _iface_block(self, iface_name: str) -> str:
        from simulator_core.types import InterfaceState
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return ""
        iface = device.interfaces.get(iface_name)
        if not iface:
            return ""
        up    = iface.admin_state == InterfaceState.UP
        proto = iface.oper_state  == InterfaceState.UP
        desc  = getattr(iface, "_description", "")
        lines = [
            f"{iface_name} is {'up' if up else 'administratively down'}, line protocol is {'up' if proto else 'down'}",
        ]
        if desc:
            lines.append(f"  Description: {desc}")
        lines.append(f"  Hardware is Ethernet, address is {iface.mac} (bia {iface.mac})")
        if iface.ip_config:
            lines.append(f"  Internet address is {iface.ip_config.address}/{iface.ip_config.prefix_length}")
        lines.append(f"  MTU 1500 bytes, BW 100000 Kbit/sec")
        lines.append(f"  Encapsulation ARPA, loopback not set")
        lines.append(f"  Full-duplex, 100Mb/s")
        lines.append(f"     {iface.rx_frames} packets input,  0 bytes,  0 no buffer")
        lines.append(f"     Received 0 broadcasts, 0 runts, 0 giants, 0 throttles")
        lines.append(f"     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored")
        lines.append(f"     {iface.tx_frames} packets output, 0 bytes, 0 underruns")
        return "\n".join(lines)

    def _cmd_show_arp(self, tokens: list[str]) -> str:
        try:
            host = self.simulation.get_host(self.device_id)
        except KeyError:
            return "% show arp is not supported on switch devices.\n  Use 'show mac address-table' instead."
        cache = host.arp_cache
        lines = ["Protocol  Address          Age (min)  Hardware Addr         Type   Interface"]
        if not cache:
            lines.append("(ARP cache is empty)")
        else:
            iface_name = list(self.simulation.topology.devices[self.device_id].interfaces.keys())[0]
            for ip, mac in cache.items():
                lines.append(f"Internet  {str(ip):<16} -          {mac}   ARPA   {iface_name}")
        return "\n".join(lines)

    def _cmd_show_mac(self, tokens: list[str]) -> str:
        try:
            switch = self.simulation.get_switch(self.device_id)
        except KeyError:
            return "% show mac address-table is only supported on switch devices."
        table = switch.mac_table
        lines = [
            "          Mac Address Table",
            "-------------------------------------------",
            "",
            "Vlan    Mac Address       Type        Ports",
            "----    -----------       --------    -----",
        ]
        if not table:
            lines.append("(empty)")
        else:
            for (mac, vlan), port in table.items():
                lines.append(f"   {vlan}    {mac}  DYNAMIC    {port}")
            lines.append(f"\nTotal Mac Addresses for this criterion: {len(table)}")
        return "\n".join(lines)

    def _cmd_show_running(self, tokens: list[str]) -> str:
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        from simulator_core.types import InterfaceState
        from ipaddress import IPv4Network as _Net
        lines = [
            "Building configuration...\n",
            "Current configuration : (NetLab Academy simulator)",
            "!",
            "version 0.1 (educational)",
            "!",
            f"hostname {device.hostname}",
            "!",
        ]
        for name, iface in device.interfaces.items():
            lines.append(f"!")
            lines.append(f"interface {name}")
            desc = getattr(iface, "_description", "")
            if desc:
                lines.append(f" description {desc}")
            if iface.ip_config:
                net = _Net(f"0.0.0.0/{iface.ip_config.prefix_length}", strict=False)
                mask = str(net.netmask)
                lines.append(f" ip address {iface.ip_config.address} {mask}")
            if iface.admin_state == InterfaceState.DOWN:
                lines.append(" shutdown")
            else:
                lines.append(" no shutdown")
        lines += ["!", "end"]
        return "\n".join(lines)

    def _cmd_show_running_iface(self, tokens: list[str], iface_name: str) -> str:
        """show running-config interface <name>"""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        iface = device.interfaces.get(iface_name)
        if not iface:
            return f"% Interface {iface_name!r} not found."
        from simulator_core.types import InterfaceState
        from ipaddress import IPv4Network as _Net
        lines = [
            "Building configuration...\n",
            "Current configuration:",
            "!",
            f"interface {iface_name}",
        ]
        desc = getattr(iface, "_description", "")
        if desc:
            lines.append(f" description {desc}")
        if iface.ip_config:
            net = _Net(f"0.0.0.0/{iface.ip_config.prefix_length}", strict=False)
            mask = str(net.netmask)
            lines.append(f" ip address {iface.ip_config.address} {mask}")
        if iface.admin_state == InterfaceState.DOWN:
            lines.append(" shutdown")
        else:
            lines.append(" no shutdown")
        lines += ["!", "end"]
        return "\n".join(lines)

    def _cmd_show_vlan_brief(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show vlan is only available on switch devices."
        vlans = switch.vlans
        lines = [
            "\nVLAN Name                             Status    Ports",
            "---- -------------------------------- --------- -------------------------------",
        ]
        for vlan_id in sorted(vlans.keys()):
            name = vlans[vlan_id]
            ports = switch.ports_in_vlan(vlan_id)
            port_str = ", ".join(ports) if ports else ""
            lines.append(f"{vlan_id:<4} {name:<32} active    {port_str}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_help(cmds: list[Cmd]) -> str:
    lines = []
    for c in cmds:
        hint = c.args_hint if c.args_hint else ("<cr>" if not c.children else "")
        if hint:
            lines.append(f"  {c.keyword:<20} {hint:<20} {c.help_str}")
        else:
            lines.append(f"  {c.keyword:<20}                      {c.help_str}")
    return "\n".join(lines)


def _invalid(tok: str) -> str:
    return (
        f"% Invalid input detected at '^' marker.\n"
        f"\n"
        f"        {tok}\n"
        f"        ^"
    )


def _invalid_at(line: str, bad_tok: str) -> str:
    idx = line.lower().rfind(bad_tok.lower())
    caret = " " * (8 + idx) + "^"
    return (
        f"% Invalid input detected at '^' marker.\n"
        f"\n"
        f"        {line}\n"
        f"{caret}"
    )


def _ambiguous(tok: str, matches: list[str]) -> str:
    return (
        f"% Ambiguous command: \"{tok}\"\n"
        f"  Possible completions: {', '.join(sorted(matches))}"
    )
