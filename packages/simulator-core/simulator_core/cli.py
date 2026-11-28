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
from simulator_core.topology import Interface
from simulator_core.types import InterfaceState

# ── Speed to STP cost mapping ──────────────────────────────────────────────────

def _speed_to_stp_cost(speed_kbps: int) -> int:
    """Map a link speed (Kbps) to an STP path cost (short method)."""
    if speed_kbps <= 10_000:
        return 100
    if speed_kbps <= 100_000:
        return 19
    if speed_kbps <= 1_000_000:
        return 4
    return 2

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
    *fallback* — when True and the next token matches no child, the
                 handler runs with the full token list instead of an
                 "invalid input" error (used where the argument is an
                 abbreviated interface name the handler resolves itself).
    """
    keyword: str
    help_str: str = ""
    children: list["Cmd"] = field(default_factory=list)
    handler: Optional[Callable[["CLISession", list[str]], str]] = None
    args_hint: str = ""
    fallback: bool = False

    def child(self, keyword: str) -> Optional["Cmd"]:
        """Return the child with the given keyword, or None."""
        for c in self.children:
            if c.keyword == keyword:
                return c
        return None


def _match(token: str, keywords: list[str]) -> list[str]:
    """
    Return all keywords that *token* is a valid prefix of.
    Case-insensitive comparison.
    Exact match wins: if token == one keyword exactly, return just that one.
    """
    tl = token.lower()
    exact = [k for k in keywords if k.lower() == tl]
    if exact:
        return exact
    return [k for k in keywords if k.lower().startswith(tl)]


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

class CLIMode(Enum):
    USER_EXEC     = auto()
    PRIV_EXEC     = auto()
    GLOBAL_CONFIG = auto()
    IFACE_CONFIG  = auto()
    VLAN_CONFIG   = auto()
    LINE_CONFIG   = auto()


# show commands that need privileged EXEC on IOS
_PRIVILEGED_SHOW = {"running-config", "startup-config", "logging"}

_CONFIG_MODES = (
    CLIMode.GLOBAL_CONFIG, CLIMode.IFACE_CONFIG,
    CLIMode.VLAN_CONFIG, CLIMode.LINE_CONFIG,
)


def _status_words(iface) -> tuple[str, str]:
    """IOS (status, protocol) words for an interface."""
    if iface.admin_state == InterfaceState.DOWN:
        return "administratively down", "down"
    if iface.oper_state == InterfaceState.UP:
        return "up", "up"
    return "down", "down"


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
    current_vlan: Optional[int] = None
    current_line: Optional[str] = None  # e.g. "console 0", "vty 0 4"
    # Pending interactive input (IOS prompts that read the next line):
    #   "press_return"  — session ended; waiting for RETURN to start a new one
    #   "login_user"    — "Username:" (login local)
    #   "login_pw"      — "Password:" for console login
    #   "enable_pw"     — "Password:" after enable
    #   "copy_dest"     — "Destination filename [startup-config]?"
    pending_input: Optional[str] = None
    _attempts: int = 0
    _login_user: Optional[str] = None
    _session_started: bool = False
    _exec_depth: int = 0
    # Highest syslog sequence already shown on this console.
    _syslog_cursor: int = 0
    # Commands typed in this session (show history)
    history: list[str] = field(default_factory=list)
    # Interfaces selected by 'interface range'; empty for a single interface.
    current_range: list[str] = field(default_factory=list)

    # ── Public API ────────────────────────────────────────────────────────────

    def drain_console(self) -> list[str]:
        """
        Syslog messages for this device not yet shown on this console, in
        order (IOS prints them asynchronously on the console line).  Returns
        nothing when console logging is off ("no logging console").
        """
        entries = self.simulation.syslog_since(self._syslog_cursor, self.device_id)
        self._syslog_cursor = self.simulation.syslog_last_seq
        config = self._get_config()
        if config is not None and not config.logging_enabled:
            return []
        return [e.text for e in entries]

    @property
    def input_hidden(self) -> bool:
        """True while the terminal must not echo what the user types."""
        return self.pending_input in ("login_pw", "enable_pw")

    def prompt(self) -> str:
        pending_prompts = {
            "press_return": "",
            "login_user": "Username: ",
            "login_pw": "Password: ",
            "enable_pw": "Password: ",
            "copy_dest": "Destination filename [startup-config]? ",
            "conf_source": "Configuring from terminal, memory, or network [terminal]? ",
        }
        if self.pending_input in pending_prompts:
            return pending_prompts[self.pending_input]
        device = self.simulation.topology.devices.get(self.device_id)
        hostname = device.hostname if device else self.device_id
        suffixes = {
            CLIMode.USER_EXEC:     ">",
            CLIMode.PRIV_EXEC:     "#",
            CLIMode.GLOBAL_CONFIG: "(config)#",
            CLIMode.IFACE_CONFIG:  "(config-if)#",
            CLIMode.VLAN_CONFIG:   "(config-vlan)#",
            CLIMode.LINE_CONFIG:   "(config-line)#",
        }
        return f"{hostname}{suffixes.get(self.mode, '>')}"

    def execute(self, raw: str) -> str:
        """
        Parse and execute a command line; returns the output text.

        Invalid-input errors are rendered IOS-style here, at the outermost
        call, with the caret aligned to the prompt the user typed at.
        """
        prompt = self.prompt()
        # Record commands (IOS includes "show history" itself) but never a
        # line typed at an interactive prompt such as a password.
        is_command = self.pending_input is None and (
            self._session_started or not self._line_requires_login()
        )
        if self._exec_depth == 0 and raw.strip() and is_command:
            self.history.append(raw.strip())
        self._exec_depth += 1
        try:
            output = self._execute(raw)
        finally:
            self._exec_depth -= 1
        if self._exec_depth == 0:
            output = _render_invalid(output, raw, prompt)
        return output

    def _execute(self, raw: str) -> str:
        """
        Parse and execute a command line.

        Returns the output string.  Never raises — unknown input returns
        the standard Cisco invalid-input error.

        Pipe filters (``| include``, ``| exclude``, ``| section``) are
        intercepted here before dispatch and applied to the output of the
        base command.  This means they work transparently for any command,
        including inside ``do`` from configuration mode.
        """
        # A new console session (or one waiting for RETURN after logout)
        # starts with the banner and, if configured, line login.
        if self.pending_input == "press_return":
            return self._start_session()
        if not self._session_started:
            # First input on a fresh terminal.  With console login configured
            # it only opens the login prompt (as pressing RETURN would);
            # otherwise the session starts silently and the command runs.
            greeting = self._start_session()
            if self.pending_input is not None:
                return greeting
        if self.pending_input is not None:
            return self._handle_pending_input(raw)

        line = raw.rstrip()
        stripped = line.strip()

        # Ctrl+Z is identical to 'end'
        if stripped == "\x1a" or stripped.lower() == "end":
            return self._cmd_end(["end"])

        if not stripped:
            return ""

        # Inline ?-help (can appear anywhere on the line)
        if stripped.endswith("?"):
            return self._inline_help(stripped)

        # ── Pipe filter extraction ────────────────────────────────────────────
        # Split on the first '|' to separate the command from its filter.
        # The pipe character is NOT a valid command token, so any '|' means
        # the user intends a filter modifier.
        pipe_filter: Optional[tuple[str, str]] = None  # (filter_type, pattern)
        if "|" in stripped:
            cmd_part, _, filter_part = stripped.partition("|")
            filter_part = filter_part.strip()
            filter_tokens = filter_part.split(None, 1)
            if filter_tokens:
                ftype = filter_tokens[0].lower()
                if ftype in ("include", "exclude", "section", "begin"):
                    pattern = filter_tokens[1] if len(filter_tokens) > 1 else ""
                    pipe_filter = (ftype, pattern)
                    stripped = cmd_part.strip()
                else:
                    # Unknown filter keyword — fall through to let dispatch report error
                    pass

        tokens = stripped.split()

        # exit/end are universal; in EXEC modes exit/logout end the session
        first = tokens[0].lower()
        if first in ("exit", "quit", "logout") and self.mode in (CLIMode.USER_EXEC, CLIMode.PRIV_EXEC):
            return self._logout()
        if first in ("exit", "end", "quit"):
            return self._cmd_end(tokens)

        was_config = self.mode in _CONFIG_MODES
        tree = self._tree()
        if self.mode == CLIMode.IFACE_CONFIG and len(self.current_range) > 1:
            output = self._dispatch_on_range(tokens, tree)
        else:
            output = self._dispatch(tokens, tree)

        # IOS: a command that is not valid in a sub-mode (interface, VLAN,
        # line) but is a valid global-configuration command runs in global
        # configuration, and the session leaves the sub-mode.  So
        # "interface g0/1" or "ip route ..." typed at (config-if)# work
        # instead of being rejected — a rejection would leave the following
        # commands applied to the previous interface.  An invalid-input
        # result has no side effects, so retrying in global mode is safe.
        if (self.mode in (CLIMode.IFACE_CONFIG, CLIMode.VLAN_CONFIG, CLIMode.LINE_CONFIG)
                and output.startswith("% Invalid input")):
            saved = (self.mode, self.current_iface, self.current_vlan,
                     self.current_line, self.current_range)
            self.mode = CLIMode.GLOBAL_CONFIG
            self.current_iface = None
            self.current_vlan = None
            self.current_line = None
            self.current_range = []
            global_output = self._dispatch(tokens, self._global_tree())
            if global_output.startswith("%"):
                # Not a usable global command either: stay in the sub-mode.
                (self.mode, self.current_iface, self.current_vlan,
                 self.current_line, self.current_range) = saved
                if not global_output.startswith("% Invalid input"):
                    output = global_output  # e.g. a bad argument to a global command
            else:
                output = global_output

        if self.mode != CLIMode.IFACE_CONFIG:
            self.current_range = []
        if was_config or self.mode in _CONFIG_MODES:
            self._refresh_l3()

        # Apply pipe filter to the output if one was specified.
        if pipe_filter:
            output = self._apply_pipe_filter(output, pipe_filter[0], pipe_filter[1])

        return output

    def _dispatch_on_range(self, tokens: list[str], tree: list[Cmd]) -> str:
        """
        Run an interface-configuration command on every interface selected
        by ``interface range`` (IOS applies the command to each member).
        Identical per-interface messages are reported once.
        """
        outputs: list[str] = []
        members = list(self.current_range)
        for name in members:
            self.current_iface = name
            out = self._dispatch(tokens, tree)
            if out and out not in outputs:
                outputs.append(out)
            if self.mode != CLIMode.IFACE_CONFIG:
                break  # the command left interface mode
        if self.mode == CLIMode.IFACE_CONFIG:
            self.current_iface = members[0]
        return "\n".join(outputs)

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
        if self.mode == CLIMode.LINE_CONFIG:
            return self._line_tree()
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
                children=[c for c in self._show_subcmds()
                          if c.keyword not in _PRIVILEGED_SHOW],
                handler=None),
            Cmd("exit",      "Exit from the EXEC",
                handler=lambda s, t: s._logout()),
            Cmd("logout",    "Exit from the EXEC",
                handler=lambda s, t: s._logout()),
            Cmd("terminal",  "Set terminal line parameters",
                children=[
                    Cmd("length", "Set number of lines on a screen",
                        args_hint="<0-512>", handler=lambda s, t: s._cmd_terminal(t)),
                    Cmd("width",  "Set width of the display terminal",
                        args_hint="<0-512>", handler=lambda s, t: s._cmd_terminal(t)),
                    Cmd("monitor", "Copy debug output to the current terminal line",
                        handler=lambda s, t: ""),
                    Cmd("no",     "Negate a command or set its defaults",
                        children=[
                            Cmd("monitor", "Stop copying debug output",
                                handler=lambda s, t: ""),
                        ]),
                ]),
        ]

    def _priv_tree(self) -> list[Cmd]:
        return [
            Cmd("configure", "Enter configuration mode",
                children=[
                    Cmd("terminal", "Enter global configuration mode",
                        handler=lambda s, t: s._cmd_conf_terminal(t)),
                ],
                # IOS: bare 'configure' asks where to configure from
                handler=lambda s, t: s._cmd_conf_prompt(t)),
            Cmd("enable",    "Enter privileged EXEC mode (already enabled)",
                handler=lambda s, t: ""),
            Cmd("terminal",  "Set terminal line parameters",
                children=[
                    Cmd("length", "Set number of lines on a screen",
                        args_hint="<0-512>", handler=lambda s, t: s._cmd_terminal(t)),
                    Cmd("width",  "Set width of the display terminal",
                        args_hint="<0-512>", handler=lambda s, t: s._cmd_terminal(t)),
                    Cmd("monitor", "Copy debug output to the current terminal line",
                        handler=lambda s, t: ""),
                    Cmd("no",     "Negate a command or set its defaults",
                        children=[
                            Cmd("monitor", "Stop copying debug output",
                                handler=lambda s, t: ""),
                        ]),
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
                    Cmd("memory",   "Write to NV memory",
                        handler=lambda s, t: s._save_startup_config()),
                    Cmd("terminal", "Write to terminal",
                        handler=lambda s, t: s._cmd_show_running(t)),
                    Cmd("erase",    "Erase the startup configuration",
                        handler=lambda s, t: s._cmd_erase_startup(t)),
                ],
                # 'write' alone defaults to 'write memory'
                handler=lambda s, t: s._save_startup_config()),
            Cmd("copy",      "Copy from one file to another",
                args_hint="running-config startup-config",
                handler=lambda s, t: s._cmd_copy(t)),
            Cmd("erase",     "Erase a filesystem",
                children=[
                    Cmd("startup-config", "Erase the startup configuration",
                        handler=lambda s, t: s._cmd_erase_startup(t)),
                ]),
            Cmd("logout",    "Exit from the EXEC",
                handler=lambda s, t: s._logout()),
            Cmd("clear",     "Reset functions",
                children=[
                    Cmd("arp",  "Delete entries from the ARP table",
                        handler=lambda s, t: ""),
                    Cmd("mac",  "MAC forwarding table",
                        children=[
                            Cmd("address-table", "MAC forwarding table",
                                children=[
                                    Cmd("dynamic", "Dynamic entries",
                                        handler=lambda s, t: s._cmd_clear_mac(t)),
                                ],
                                handler=lambda s, t: s._cmd_clear_mac(t)),
                        ]),
                ]),
            Cmd("exit",      "Exit from the EXEC",
                handler=lambda s, t: s._logout()),
        ]

    def _global_tree(self) -> list[Cmd]:
        return [
            Cmd("hostname",   "Set system's network name",
                args_hint="<hostname>",
                handler=lambda s, t: s._cmd_hostname(t)),
            Cmd("spanning-tree", "Spanning tree configuration",
                children=[
                    Cmd("mode",    "Set STP mode",
                        children=[
                            Cmd("pvst",       "PVST+ mode",
                                handler=lambda s, t: s._cmd_stp_mode(t, "pvst")),
                            Cmd("rapid-pvst", "Rapid PVST+ mode",
                                handler=lambda s, t: s._cmd_stp_mode(t, "rapid-pvst")),
                            Cmd("mst",        "MSTP mode",
                                handler=lambda s, t: s._cmd_stp_mode(t, "mst")),
                        ]),
                    Cmd("vlan",    "VLAN spanning tree settings",
                        args_hint="<vlan-id> priority|root ...",
                        handler=lambda s, t: s._cmd_stp_global_vlan(t)),
                    Cmd("portfast", "Global PortFast settings",
                        children=[
                            Cmd("default", "Enable PortFast on all access ports",
                                handler=lambda s, t: s._cmd_stp_portfast_default(t)),
                            Cmd("bpduguard", "Enable BPDU Guard globally",
                                children=[
                                    Cmd("default", "Enable globally",
                                        handler=lambda s, t: s._cmd_stp_bpduguard_default(t)),
                                ]),
                        ]),
                    Cmd("backbonefast", "BackboneFast (no-op in sim)",
                        handler=lambda s, t: ""),
                    Cmd("uplinkfast",   "UplinkFast (no-op in sim)",
                        handler=lambda s, t: ""),
                    Cmd("pathcost",     "Global path-cost method",
                        children=[
                            Cmd("method", "Path-cost method",
                                children=[
                                    Cmd("short", "16-bit short method",
                                        handler=lambda s, t: ""),
                                    Cmd("long",  "32-bit long method",
                                        handler=lambda s, t: ""),
                                ]),
                        ]),
                ]),
            Cmd("interface",  "Select an interface to configure",
                args_hint="<interface-name> | range | vlan | loopback",
                handler=lambda s, t: s._cmd_enter_iface(t)),
            Cmd("vlan",       "Configure a VLAN",
                args_hint="<vlan-id>",
                handler=lambda s, t: s._cmd_enter_vlan(t)),
            Cmd("line",       "Configure a terminal line",
                args_hint="[console|vty|aux] <first> [last]",
                handler=lambda s, t: s._cmd_enter_line(t)),
            Cmd("username",   "Establish User Name Authentication",
                args_hint="<name> privilege <0-15> secret <password>",
                handler=lambda s, t: s._cmd_username(t)),
            Cmd("enable",     "Modify enable password parameters",
                children=[
                    Cmd("secret",   "Assign the privileged level secret",
                        args_hint="<password>",
                        handler=lambda s, t: s._cmd_enable_secret(t)),
                    Cmd("password", "Assign the privileged level password",
                        args_hint="<password>",
                        handler=lambda s, t: s._cmd_enable_password(t)),
                ]),
            Cmd("no",         "Negate a command or set its defaults",
                children=[
                    Cmd("vlan", "Delete a VLAN",
                        args_hint="<vlan-id>",
                        handler=lambda s, t: s._cmd_no_vlan(t)),
                    Cmd("ip",   "Negate IP configuration",
                        children=[
                            Cmd("route", "Remove a static route",
                                args_hint="<network> <mask> <next-hop>",
                                handler=lambda s, t: s._cmd_no_ip_route(t)),
                            Cmd("default-gateway", "Remove default gateway",
                                handler=lambda s, t: s._cmd_no_ip_default_gateway(t)),
                            Cmd("domain-lookup", "Disable DNS lookups",
                                handler=lambda s, t: s._cmd_no_ip_domain_lookup(t)),
                        ]),
                    Cmd("hostname", "Reset hostname",
                        handler=lambda s, t: s._cmd_hostname(["hostname", "Router"])),
                    Cmd("enable", "Remove enable password",
                        children=[
                            Cmd("secret",   "Remove enable secret",
                                handler=lambda s, t: s._cmd_no_enable_secret(t)),
                            Cmd("password", "Remove enable password",
                                handler=lambda s, t: s._cmd_no_enable_password(t)),
                        ]),
                    Cmd("username", "Remove a user account",
                        args_hint="<name>",
                        handler=lambda s, t: s._cmd_no_username(t)),
                    Cmd("logging", "Remove a logging destination",
                        args_hint="<host>",
                        handler=lambda s, t: s._cmd_no_logging(t)),
                    Cmd("cdp",    "Disable CDP",
                        children=[
                            Cmd("run",  "Disable CDP globally",
                                handler=lambda s, t: s._cmd_cdp_run(t, False)),
                        ]),
                ]),
            Cmd("ip",         "IP configuration",
                children=[
                    Cmd("routing", "Enable IP routing",
                        handler=lambda s, t: ""),
                    Cmd("route",   "Establish a static route",
                        args_hint="<network> <mask> <next-hop>",
                        handler=lambda s, t: s._cmd_ip_route(t)),
                    Cmd("default-gateway", "Specify default gateway (for L2 switches)",
                        args_hint="<ip-address>",
                        handler=lambda s, t: s._cmd_ip_default_gateway(t)),
                    Cmd("domain-lookup", "Enable DNS lookups",
                        handler=lambda s, t: s._cmd_ip_domain_lookup(t)),
                    Cmd("domain-name", "Define the default domain name",
                        args_hint="<name>",
                        handler=lambda s, t: s._cmd_ip_domain_name(t)),
                ]),
            Cmd("logging",    "Modify message logging facilities",
                args_hint="[buffered|console|host|on|synchronous] ...",
                handler=lambda s, t: s._cmd_logging(t)),
            Cmd("service",    "Modify use of network based services",
                children=[
                    Cmd("password-encryption", "Encrypt system passwords",
                        handler=lambda s, t: s._cmd_service_password_encryption(t)),
                    Cmd("timestamps",          "Timestamp debug/log messages",
                        handler=lambda s, t: ""),
                ]),
            Cmd("cdp",        "Configure CDP",
                children=[
                    Cmd("run",      "Enable CDP globally",
                        handler=lambda s, t: s._cmd_cdp_run(t, True)),
                    Cmd("timer",    "Set CDP advertisement interval",
                        args_hint="<seconds>",
                        handler=lambda s, t: s._cmd_cdp_timer(t)),
                    Cmd("holdtime", "Set CDP holdtime",
                        args_hint="<seconds>",
                        handler=lambda s, t: s._cmd_cdp_holdtime(t)),
                ]),
            Cmd("banner",     "Define a login banner",
                args_hint="motd | login | exec",
                handler=lambda s, t: s._cmd_banner(t)),
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
                        children=[
                            Cmd("nonegotiate", "Re-enable DTP negotiation",
                                handler=lambda s, t: s._cmd_switchport_nonegotiate(t, False)),
                        ],
                        fallback=True,
                        handler=lambda s, t: s._cmd_no_switchport(t)),
                    Cmd("cdp",       "Disable CDP on this interface",
                        children=[
                            Cmd("enable", "Disable CDP on this interface",
                                handler=lambda s, t: s._cmd_cdp_iface_enable(t, False)),
                        ]),
                ]),
            Cmd("encapsulation", "Set encapsulation type for a subinterface",
                children=[
                    Cmd("dot1Q", "IEEE 802.1Q Virtual LAN",
                        args_hint="<vlan-id> [native]",
                        handler=lambda s, t: s._cmd_encapsulation_dot1q(t)),
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
                            Cmd("access",  "Set access mode",
                                handler=lambda s, t: s._cmd_switchport_mode_access(t)),
                            Cmd("trunk",   "Set trunk mode",
                                handler=lambda s, t: s._cmd_switchport_mode_trunk(t)),
                            Cmd("dynamic", "Set dynamic negotiation mode",
                                children=[
                                    Cmd("auto",      "Set to dynamic auto",
                                        handler=lambda s, t: s._cmd_switchport_mode_dynamic(t, "auto")),
                                    Cmd("desirable", "Set to dynamic desirable",
                                        handler=lambda s, t: s._cmd_switchport_mode_dynamic(t, "desirable")),
                                ]),
                        ]),
                    Cmd("access", "Set access VLAN",
                        children=[
                            Cmd("vlan", "Assign access VLAN",
                                args_hint="<vlan-id>",
                                handler=lambda s, t: s._cmd_switchport_access_vlan(t)),
                        ]),
                    Cmd("trunk",  "Trunk configuration",
                        children=[
                            Cmd("native",  "Set native VLAN on trunk",
                                children=[
                                    Cmd("vlan", "Native VLAN",
                                        args_hint="<vlan-id>",
                                        handler=lambda s, t: s._cmd_switchport_trunk_native_vlan(t)),
                                ]),
                            Cmd("allowed", "Set allowed VLANs on trunk",
                                children=[
                                    Cmd("vlan", "Allowed VLANs",
                                        args_hint="<vlan-list>",
                                        handler=lambda s, t: s._cmd_switchport_trunk_allowed_vlan(t)),
                                ]),
                            Cmd("encapsulation", "Set trunk encapsulation",
                                children=[
                                    Cmd("dot1q", "IEEE 802.1Q encapsulation",
                                        handler=lambda s, t: s._cmd_switchport_trunk_encap(t, "dot1q")),
                                    Cmd("isl",   "ISL encapsulation (not simulated)",
                                        handler=lambda s, t: "% ISL encapsulation is not supported."),
                                ]),
                            Cmd("pruning", "Prune VLANs from trunk (no-op in sim)",
                                handler=lambda s, t: ""),
                        ]),
                    Cmd("nonegotiate", "Device will not engage in negotiation protocol on this interface",
                        handler=lambda s, t: s._cmd_switchport_nonegotiate(t, True)),
                    Cmd("port-security", "Enable port security",
                        handler=lambda s, t: s._cmd_switchport_port_security(t)),
                ]),
            Cmd("spanning-tree", "Spanning tree configuration",
                children=[
                    Cmd("portfast",    "Enable PortFast on this interface",
                        children=[
                            Cmd("disable", "Disable PortFast",
                                handler=lambda s, t: s._cmd_stp_portfast(t, False)),
                            Cmd("trunk",   "Enable PortFast on trunk (no-op)",
                                handler=lambda s, t: ""),
                        ],
                        handler=lambda s, t: s._cmd_stp_portfast(t, True)),
                    Cmd("bpduguard",   "BPDU guard",
                        children=[
                            Cmd("enable",  "Enable BPDU guard",
                                handler=lambda s, t: s._cmd_stp_bpduguard(t, True)),
                            Cmd("disable", "Disable BPDU guard",
                                handler=lambda s, t: s._cmd_stp_bpduguard(t, False)),
                        ]),
                    Cmd("bpdufilter",  "BPDU filter",
                        children=[
                            Cmd("enable",  "Enable BPDU filter",
                                handler=lambda s, t: s._cmd_stp_bpdufilter(t, True)),
                            Cmd("disable", "Disable BPDU filter",
                                handler=lambda s, t: s._cmd_stp_bpdufilter(t, False)),
                        ]),
                    Cmd("guard",       "Spanning tree guard",
                        children=[
                            Cmd("root", "Enable root guard",
                                handler=lambda s, t: s._cmd_stp_guard(t, "root")),
                            Cmd("loop", "Enable loop guard",
                                handler=lambda s, t: s._cmd_stp_guard(t, "loop")),
                            Cmd("none", "Disable guard",
                                handler=lambda s, t: s._cmd_stp_guard(t, "none")),
                        ]),
                    Cmd("cost",        "Port path cost",
                        args_hint="<1-200000000>",
                        handler=lambda s, t: s._cmd_stp_port_cost(t)),
                    Cmd("port-priority", "Port priority",
                        args_hint="<0-240>",
                        handler=lambda s, t: s._cmd_stp_port_priority_iface(t)),
                    Cmd("vlan",        "VLAN-specific STP settings",
                        args_hint="<vlan-id> cost|port-priority <value>",
                        handler=lambda s, t: s._cmd_stp_iface_vlan(t)),
                ]),
            Cmd("channel-group", "Assign this interface to a port-channel",
                args_hint="<1-6> mode <on|active|passive|desirable|auto>",
                handler=lambda s, t: s._cmd_channel_group(t)),
            Cmd("channel-protocol", "EtherChannel protocol (lacp/pagp)",
                args_hint="<lacp|pagp>",
                handler=lambda s, t: ""),
            Cmd("cdp",         "CDP interface configuration",
                children=[
                    Cmd("enable", "Enable CDP on this interface",
                        handler=lambda s, t: s._cmd_cdp_iface_enable(t, True)),
                ]),
            Cmd("speed",       "Configure interface speed",
                args_hint="<10|100|1000|10000|auto>",
                handler=lambda s, t: s._cmd_iface_speed(t)),
            Cmd("duplex",      "Configure duplex operation",
                children=[
                    Cmd("auto", "Auto-duplex",
                        handler=lambda s, t: s._cmd_iface_duplex(t, "auto")),
                    Cmd("full", "Full-duplex",
                        handler=lambda s, t: s._cmd_iface_duplex(t, "full")),
                    Cmd("half", "Half-duplex",
                        handler=lambda s, t: s._cmd_iface_duplex(t, "half")),
                ]),
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

    def _line_tree(self) -> list[Cmd]:
        return [
            Cmd("login",          "Enable password checking",
                handler=lambda s, t: s._cmd_line_login(t)),
            Cmd("password",       "Set a password on the line",
                args_hint="<password>",
                handler=lambda s, t: s._cmd_line_password(t)),
            Cmd("exec-timeout",   "Set the EXEC command-line idle timeout",
                args_hint="<minutes> [seconds]",
                handler=lambda s, t: s._cmd_line_exec_timeout(t)),
            Cmd("logging",        "Control logging to this line",
                children=[
                    Cmd("synchronous", "Synchronous logging output",
                        handler=lambda s, t: s._cmd_line_logging_sync(t)),
                ]),
            Cmd("transport",      "Define transport protocols for a line",
                children=[
                    Cmd("input", "Define input transport protocols",
                        args_hint="<protocol>",
                        handler=lambda s, t: s._cmd_line_transport(t)),
                ]),
            Cmd("privilege",      "Change the current privilege level for this line",
                args_hint="<level>",
                handler=lambda s, t: s._cmd_line_privilege(t)),
            Cmd("no",            "Negate a command",
                children=[
                    Cmd("login", "Disable password checking",
                        handler=lambda s, t: s._cmd_line_no_login(t)),
                    Cmd("password", "Remove password",
                        handler=lambda s, t: s._cmd_line_no_password(t)),
                    Cmd("exec-timeout", "Remove timeout",
                        handler=lambda s, t: s._cmd_line_no_exec_timeout(t)),
                    Cmd("logging",  "Disable logging",
                        children=[
                            Cmd("synchronous", "Disable synchronous logging",
                                handler=lambda s, t: s._cmd_line_no_logging_sync(t)),
                        ]),
                ]),
            Cmd("do",            "Run an EXEC command from config mode",
                args_hint="<exec-command>",
                handler=lambda s, t: s._cmd_do(t)),
            Cmd("exit",          "Exit from line configuration mode",
                handler=lambda s, t: s._cmd_end(t)),
            Cmd("end",           "End and return to privileged EXEC",
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
                        ],
                        # Also handle abbreviated name via the parent handler
                        handler=lambda s, t: s._show_ip_iface_dispatch(t),
                        fallback=True),
                    Cmd("route",     "IP routing table",
                        handler=lambda s, t: s._cmd_show_ip_route(t)),
                    Cmd("arp",       "IP ARP table",
                        handler=lambda s, t: s._cmd_show_arp(t)),
                ]),
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
                        args_hint="<interface-name>",
                        handler=lambda s, t: s._show_running_iface_dispatch(t)),
                ],
                handler=lambda s, t: s._cmd_show_running(t)),
            Cmd("startup-config", "Contents of startup configuration",
                handler=lambda s, t: s._cmd_show_startup(t)),
            Cmd("vlan",        "VTP VLAN status",
                children=[
                    Cmd("brief", "VTP management domain status",
                        handler=lambda s, t: s._cmd_show_vlan_brief(t)),
                ],
                handler=lambda s, t: s._cmd_show_vlan(t)),
            Cmd("cdp",         "CDP information",
                children=[
                    Cmd("neighbors", "CDP neighbor information",
                        children=[
                            Cmd("detail", "Show detailed CDP neighbor information",
                                handler=lambda s, t: s._cmd_show_cdp_neighbors_detail(t)),
                        ],
                        handler=lambda s, t: s._cmd_show_cdp_neighbors(t)),
                    Cmd("interface", "CDP interface status",
                        handler=lambda s, t: s._cmd_show_cdp_interface(t)),
                    Cmd("entry",     "CDP entry for a specific neighbor",
                        args_hint="*",
                        handler=lambda s, t: s._cmd_show_cdp_neighbors_detail(t)),
                ],
                handler=lambda s, t: s._cmd_show_cdp(t)),
            Cmd("clock",       "Display the system clock",
                handler=lambda s, t: f"% Logical clock: tick {self.simulation.clock}"),
            Cmd("history",     "Display the session command history",
                handler=lambda s, t: "\n".join(f"  {c}" for c in s.history[-10:])),
            Cmd("logging",     "Display logging information",
                handler=lambda s, t: s._cmd_show_logging(t)),
            Cmd("users",        "Display information about terminal lines",
                handler=lambda s, t: s._cmd_show_users(t)),
            Cmd("spanning-tree", "Spanning tree information",
                children=[
                    Cmd("summary", "Summary of port states",
                        handler=lambda s, t: s._cmd_show_stp_summary(t)),
                    Cmd("detail",  "Detailed STP state",
                        handler=lambda s, t: s._cmd_show_stp_vlan(t, None)),
                    Cmd("vlan",    "Per-VLAN spanning tree state",
                        args_hint="<vlan-id>",
                        handler=lambda s, t: s._cmd_show_stp_vlan_dispatch(t)),
                    Cmd("active",  "Active ports in spanning tree",
                        handler=lambda s, t: s._cmd_show_stp_summary(t)),
                ],
                handler=lambda s, t: s._cmd_show_stp_vlan(t, None)),
            Cmd("etherchannel", "EtherChannel information",
                children=[
                    Cmd("summary",      "EtherChannel summary",
                        handler=lambda s, t: s._cmd_show_etherchannel_summary(t)),
                    Cmd("detail",       "EtherChannel detail",
                        handler=lambda s, t: s._cmd_show_etherchannel_detail(t)),
                    Cmd("port-channel", "Port-channel detail",
                        handler=lambda s, t: s._cmd_show_etherchannel_detail(t)),
                    Cmd("neighbors",    "LACP/PAgP neighbor information",
                        handler=lambda s, t: s._cmd_show_etherchannel_neighbors(t)),
                    Cmd("protocol",     "EtherChannel protocol",
                        handler=lambda s, t: s._cmd_show_etherchannel_summary(t)),
                ],
                handler=lambda s, t: s._cmd_show_etherchannel_summary(t)),
            Cmd("port-channel", "EtherChannel info (alias)",
                handler=lambda s, t: s._cmd_show_etherchannel_summary(t)),
            Cmd("interfaces",   "Show interfaces (with trunk support)",
                children=[
                    Cmd("trunk",   "Show trunk interfaces",
                        handler=lambda s, t: s._cmd_show_interfaces_trunk(t)),
                    Cmd("switchport", "Show interface switchport information",
                        handler=lambda s, t: s._cmd_show_switchport(None)),
                    Cmd("status",  "Brief interface status",
                        handler=lambda s, t: s._cmd_show_interfaces_status(t)),
                    Cmd("brief",   "Brief IP interface summary",
                        handler=lambda s, t: s._cmd_show_ip_int_brief(t)),
                ] + [
                    Cmd(name, f"Interface {name}",
                        handler=lambda s, t, n=name: s._cmd_show_interface(t, n))
                    for name in self._iface_names()
                ],
                handler=lambda s, t: s._show_interfaces_dispatch(t),
                fallback=True),
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
        parent_fallback: Optional[Cmd] = None

        for depth, tok in enumerate(tokens):
            keywords = [c.keyword for c in node_list]
            matches = _match(tok.lower(), keywords)

            if len(matches) == 0:
                if depth > 0 and parent_fallback is not None:
                    return parent_fallback.handler(self, tokens)
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
                parent_fallback = cmd_node if cmd_node.fallback else None
                continue

            # Node has only children (no handler).
            if not cmd_node.children:
                # Dead end with no handler
                return _invalid(" ".join(tokens))

            if not remaining:
                # Stopped mid-tree with no handler
                return f"% Incomplete command."

            node_list = cmd_node.children
            parent_fallback = None

        # Fell off the end of tokens mid-tree
        return "% Incomplete command."

    # ── Inline ? help ─────────────────────────────────────────────────────────

    def _inline_help(self, line: str) -> str:
        """
        Generate context-sensitive help for a line ending with '?'.
        Mirrors IOS: 'show ?' lists sub-commands of show.
        """
        # Remove trailing ?
        word_help = not line[:-1].endswith(" ") and line[:-1].strip() != ""
        before = line.rstrip("?").rstrip()
        tokens = before.split() if before else []

        tree = self._tree()
        node_list = tree

        if not tokens:
            # '?' at the start of a blank line
            return _format_help(node_list)

        if word_help:
            # IOS: "sh?" lists the keywords that start with "sh" at that
            # position (word help), not the arguments of the command.
            for tok in tokens[:-1]:
                found = _match(tok.lower(), [c.keyword for c in node_list])
                if len(found) != 1:
                    return "% Unrecognized command"
                node_list = next(c for c in node_list if c.keyword == found[0]).children
            partial = tokens[-1].lower()
            words = [c.keyword for c in node_list if c.keyword.lower().startswith(partial)]
            return "  ".join(words) if words else "% Unrecognized command"

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

    # ── Pipe filter ───────────────────────────────────────────────────────────

    def _apply_pipe_filter(self, output: str, ftype: str, pattern: str) -> str:
        """
        Apply a Cisco-style output filter to a command's output.

        Supported filters:
          include <pattern>  — keep only lines containing pattern
          exclude <pattern>  — remove lines containing pattern
          section <pattern>  — keep the section header matching pattern
                               plus all indented lines following it
          begin   <pattern>  — keep lines from the first match onward

        The pattern is a case-sensitive regular expression, as on IOS, so
        ``include ip|vlan`` keeps lines matching either word and
        ``include Vlan`` does not match ``vlan``.  An invalid expression
        falls back to a plain substring match.
        """
        if not output:
            return output
        lines = output.splitlines()
        try:
            rx = re.compile(pattern)
            matches = lambda line: rx.search(line) is not None  # noqa: E731
        except re.error:
            matches = lambda line: pattern in line  # noqa: E731

        if ftype == "include":
            return "\n".join(l for l in lines if matches(l))

        if ftype == "exclude":
            return "\n".join(l for l in lines if not matches(l))

        if ftype == "begin":
            result: list[str] = []
            started = False
            for l in lines:
                if not started and matches(l):
                    started = True
                if started:
                    result.append(l)
            return "\n".join(result)

        if ftype == "section":
            result = []
            in_section = False
            for l in lines:
                if matches(l) and not l.startswith(" "):
                    in_section = True
                    result.append(l)
                elif in_section:
                    if l.startswith(" ") or l.startswith("\t") or not l.strip():
                        result.append(l)
                    else:
                        in_section = False
            return "\n".join(result)

        return output

    def _cmd_end(self, tokens: list[str]) -> str:
        cmd = tokens[0].lower() if tokens else "exit"

        # `end` (and Ctrl+Z) jumps to PRIV_EXEC from any *config* submode.
        # It must NOT elevate privileges from USER_EXEC.
        if cmd == "end":
            if self.mode in (
                CLIMode.GLOBAL_CONFIG,
                CLIMode.IFACE_CONFIG,
                CLIMode.VLAN_CONFIG,
                CLIMode.LINE_CONFIG,
            ):
                self._log_config_exit()
                self.mode = CLIMode.PRIV_EXEC
                self.current_iface = None
                self.current_vlan  = None
                self.current_line  = None
            # In USER_EXEC or PRIV_EXEC, 'end' is a no-op (matches IOS: ignored
            # in EXEC modes rather than raising an error).
            return ""

        # `exit` goes one level back.
        if self.mode == CLIMode.IFACE_CONFIG:
            self.mode = CLIMode.GLOBAL_CONFIG
            self.current_iface = None
        elif self.mode == CLIMode.VLAN_CONFIG:
            self.mode = CLIMode.GLOBAL_CONFIG
            self.current_vlan = None
        elif self.mode == CLIMode.LINE_CONFIG:
            self.mode = CLIMode.GLOBAL_CONFIG
            self.current_line = None
        elif self.mode == CLIMode.GLOBAL_CONFIG:
            self._log_config_exit()
            self.mode = CLIMode.PRIV_EXEC
        elif self.mode == CLIMode.PRIV_EXEC:
            self.mode = CLIMode.USER_EXEC
        # USER_EXEC exit: caller decides (close terminal); no mode change here.
        return ""

    def _cmd_enable(self, tokens: list[str]) -> str:
        config = self._get_config()
        if (self.mode == CLIMode.USER_EXEC and config is not None
                and (config.enable_secret_hash or config.enable_password_hash)):
            self.pending_input = "enable_pw"
            self._attempts = 0
            return ""
        if self.mode == CLIMode.USER_EXEC and config is not None and self._line_requires_login():
            # IOS: with a line login but no enable password, enable is refused
            return "% No password set"
        self.mode = CLIMode.PRIV_EXEC
        return ""

    # ── Sessions, login and interactive prompts ────────────────────────────────

    def _line_requires_login(self) -> bool:
        config = self._get_config()
        if config is None:
            return False
        con = config.console_line
        return bool(con.login_local or (con.login and con.password_hash))

    def _banner(self) -> str:
        config = self._get_config()
        if config is not None and config.banner_motd:
            return config.banner_motd + "\n"
        return ""

    def _start_session(self) -> str:
        """
        Begin a console session: show the MOTD banner, then ask for line
        credentials when the console line has ``login`` (with a password)
        or ``login local``.  Configuration changes apply to new sessions,
        as on IOS.
        """
        self._session_started = True
        self.pending_input = None
        self.mode = CLIMode.USER_EXEC
        self.current_iface = self.current_vlan = self.current_line = None
        self.current_range = []
        self._attempts = 0
        out = self._banner()
        config = self._get_config()
        if config is not None and config.console_line.login_local:
            self.pending_input = "login_user"
            return out + "\nUser Access Verification\n"
        if config is not None and config.console_line.login and config.console_line.password_hash:
            self.pending_input = "login_pw"
            return out + "\nUser Access Verification\n"
        return out.rstrip("\n")

    def _log_config_exit(self) -> None:
        """IOS logs %SYS-5-CONFIG_I when a user leaves configuration mode."""
        from simulator_core.types import DeviceModel
        device = self.simulation.topology.devices.get(self.device_id)
        if device is not None and device.model in (DeviceModel.SWITCH, DeviceModel.ROUTER):
            self.simulation.log_event(self.device_id, "SYS", 5, "CONFIG_I",
                                      "Configured from console by console")

    def _logout(self) -> str:
        device = self.simulation.topology.devices.get(self.device_id)
        hostname = device.hostname if device else self.device_id
        self.mode = CLIMode.USER_EXEC
        self.pending_input = "press_return"
        return f"\n{hostname} con0 is now available\n\n\n\n\nPress RETURN to get started."

    def _handle_pending_input(self, raw: str) -> str:
        config = self._get_config()
        kind = self.pending_input
        value = raw.strip()

        if kind == "conf_source":
            self.pending_input = None
            if value == "" or "terminal".startswith(value.lower()):
                return self._cmd_conf_terminal([])
            return "% Only configuring from the terminal is supported in this simulator."

        if kind == "copy_dest":
            self.pending_input = None
            if value and value != "startup-config":
                return f"% Only startup-config is supported as a destination in this simulator."
            return self._save_startup_config()

        if kind == "enable_pw":
            if config is not None and config.check_enable(value):
                self.pending_input = None
                self.mode = CLIMode.PRIV_EXEC
                return ""
            self._attempts += 1
            if self._attempts >= 3:
                self.pending_input = None
                return "% Bad secrets\n"
            return ""

        if kind == "login_user":
            self._login_user = value
            self.pending_input = "login_pw"
            return ""

        if kind == "login_pw":
            con = config.console_line if config is not None else None
            ok = False
            privilege = con.privilege if con is not None else 1
            if con is not None and con.login_local:
                user = config.users.get(self._login_user or "")
                ok = user is not None and user.check_password(value)
                if ok:
                    privilege = user.privilege
            elif con is not None:
                ok = con.check_password(value)
            if ok:
                self.pending_input = None
                self._attempts = 0
                self.mode = CLIMode.PRIV_EXEC if privilege >= 15 else CLIMode.USER_EXEC
                return ""
            self._attempts += 1
            if self._attempts >= 3:
                return "% Bad passwords\n" + self._logout()
            if con is not None and con.login_local:
                self.pending_input = "login_user"
                return "% Login invalid\n"
            return ""

        self.pending_input = None
        return ""

    # ── startup-config ──────────────────────────────────────────────────────────

    def _running_config_text(self) -> str:
        text = self._cmd_show_running([])
        return text.split("\n", 2)[2] if text.startswith("Building configuration") else text

    def _save_startup_config(self) -> str:
        config = self._get_config()
        if config is None:
            return "% Device not found."
        config.startup_config = self._running_config_text()
        return "Building configuration...\n[OK]"

    def _cmd_copy(self, tokens: list[str]) -> str:
        # copy running-config startup-config | copy run start
        if len(tokens) < 3:
            return "% Incomplete command."
        src, dst = tokens[1].lower(), tokens[2].lower()
        if "running-config".startswith(src) and "startup-config".startswith(dst):
            self.pending_input = "copy_dest"
            return ""
        if "startup-config".startswith(src) and "running-config".startswith(dst):
            return "% Merging startup-config into running-config is not supported in this simulator."
        return _invalid_at(" ".join(tokens[:2]), tokens[1])

    def _cmd_show_startup(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None or config.startup_config is None:
            return "startup-config is not present"
        size = len(config.startup_config.encode())
        return f"Using {size} out of 65536 bytes\n{config.startup_config}"

    def _cmd_erase_startup(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is not None:
            config.startup_config = None
        return ("Erasing the nvram filesystem will remove all configuration files! "
                "Continue? [confirm]\n[OK]\nErase of nvram: complete")

    def _cmd_conf_prompt(self, tokens: list[str]) -> str:
        self.pending_input = "conf_source"
        return ""

    def _cmd_terminal(self, tokens: list[str]) -> str:
        # terminal length|width <0-512> — accepted; output is never paged here
        if len(tokens) < 3:
            return "% Incomplete command."
        if not tokens[2].isdigit() or not 0 <= int(tokens[2]) <= 512:
            return _invalid_at(" ".join(tokens[:3]), tokens[2])
        return ""

    def _cmd_clear_mac(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return _invalid_at(" ".join(tokens[:2]), tokens[1])
        switch.clear_dynamic_mac_addresses()
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

    def _cmd_do(self, tokens: list[str]) -> str:
        """do <exec-command> — run EXEC command from config mode."""
        if len(tokens) < 2:
            return "% Incomplete command."
        # Reconstruct the original command string after 'do' — this preserves
        # any pipe filters (| include, | exclude, etc.) that would be lost if
        # we only forwarded the pre-split token list.
        saved_mode = self.mode
        saved_iface = self.current_iface
        self.mode = CLIMode.PRIV_EXEC
        # Re-join everything after 'do' and run it through the full execute()
        # pipeline, which handles pipe filters correctly.
        sub_command = " ".join(tokens[1:])
        result = self.execute(sub_command)
        self.mode = saved_mode
        self.current_iface = saved_iface
        # Keep caret positions relative to the whole "do ..." line
        return result.replace(_INVALID_HEADER + "\x00", _INVALID_HEADER + "\x00do ")

    # ── Interface config commands ──────────────────────────────────────────────

    def _get_current_iface(self):
        device = self.simulation.topology.devices.get(self.device_id)
        return device.interfaces.get(self.current_iface) if device and self.current_iface else None

    def _refresh_l3(self) -> None:
        """
        Recompute interface line-protocol state and rebuild router connected
        routes (re-resolving static routes) after a configuration change.

        A change on one device can change line protocol on its neighbour
        (``shutdown`` takes the peer port down too), so the whole
        simulation is refreshed, not just this device.
        """
        self.simulation.refresh_interface_states()

    def _require_physical_switchport(self) -> Optional[str]:
        """
        Return an IOS-style error string if the current interface is NOT a
        physical switchport (i.e. it is an SVI or loopback).  Return None
        if the check passes.

        Call this at the top of every switchport command handler.
        """
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        if iface.is_svi:
            # IOS positions the caret under the first invalid token.
            return (
                _invalid("switchport")
                + "\n% SVI interfaces (Vlan) do not support switchport commands."
            )
        if iface.is_loopback:
            return (
                _invalid("switchport")
                + "\n% Loopback interfaces do not support switchport commands."
            )
        return None

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

    # ── Interface speed / duplex ────────────────────────────────────────────────

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

    # ── Static routing commands ───────────────────────────────────────────────

    def _get_router(self):
        """Return the Router object for this session, or None."""
        try:
            return self.simulation.get_router(self.device_id)
        except KeyError:
            return None

    def _parse_network_and_mask(self, net_str: str, mask_str: str):
        """
        Parse a network + dotted-mask pair, return IPv4Network or None.
        The mask must be contiguous and the network must have no host bits
        set (IOS: "%Inconsistent address and mask").
        """
        from ipaddress import IPv4Address, IPv4Network
        try:
            prefix = _mask_prefix(int(IPv4Address(mask_str)))
            if prefix is None:
                return None
            return IPv4Network(f"{net_str}/{prefix}", strict=True)
        except Exception:
            return None

    def _cmd_ip_route(self, tokens: list[str]) -> str:
        # ip route <network> <mask> {<next-hop> | <interface> [<next-hop>]}
        if len(tokens) < 5:
            return "% Incomplete command.\nUsage: ip route <network> <mask> {<next-hop> | <interface> [<next-hop>]}"
        tokens = _join_iface_tokens(tokens, 4)
        net_str, mask_str = tokens[2], tokens[3]
        network = self._parse_network_and_mask(net_str, mask_str)
        if network is None:
            return "%Inconsistent address and mask"
        router = self._get_router()
        if router is None:
            return "% ip route is only available on router devices."
        from ipaddress import IPv4Address
        next_hop = None
        exit_iface = None
        try:
            next_hop = IPv4Address(tokens[4])
        except ValueError:
            device = self.simulation.topology.devices[self.device_id]
            found = _match_iface(tokens[4], list(device.interfaces))
            if len(found) != 1:
                return _invalid_at(" ".join(tokens[:5]), tokens[4])
            exit_iface = found[0]
            if len(tokens) > 5:
                try:
                    next_hop = IPv4Address(tokens[5])
                except ValueError:
                    return _invalid_at(" ".join(tokens[:6]), tokens[5])
        # Outgoing interfaces are resolved from the connected routes.  As on
        # IOS, a static route that cannot be resolved yet is kept in the
        # configuration but not installed until it can be.
        router.routing_table.add_static_route(network, next_hop, "", exit_interface=exit_iface)
        router.routing_table.resolve_static_routes()
        return ""

    def _cmd_no_ip_route(self, tokens: list[str]) -> str:
        # tokens: ['no', 'ip', 'route', '<network>', '<mask>']
        if len(tokens) < 5:
            return "% Incomplete command.\nUsage: no ip route <network> <mask> <next-hop>"
        net_str, mask_str = tokens[3], tokens[4]
        network = self._parse_network_and_mask(net_str, mask_str)
        if network is None:
            return f"% Invalid network or mask: {net_str} {mask_str}"
        router = self._get_router()
        if router is None:
            return "% ip route is only available on router devices."
        if not router.routing_table.remove_static_route(network):
            return f"% Route {network} not found."
        return ""

    # ── Switchport commands ───────────────────────────────────────────────────

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

    def _cmd_switchport_port_security(self, tokens: list[str]) -> str:
        """Basic port security (store config; enforcement not yet simulated)."""
        err = self._require_physical_switchport()
        if err:
            return err
        iface = self._get_current_iface()
        if iface:
            iface._port_security_enabled = True  # type: ignore[attr-defined]
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
        try:
            switch.set_port_vlan(self.current_iface, vlan_id)
        except ValueError as exc:
            return f"% {exc}"
        return ""

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

    # ── STP per-interface commands ────────────────────────────────────────────

    def _cmd_stp_portfast(self, tokens: list[str], enabled: bool) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        iface_name = self.current_iface
        if iface_name is None:
            return "% No interface selected."
        switch.stp.set_portfast(iface_name, enabled)
        return ""

    def _cmd_stp_bpduguard(self, tokens: list[str], enabled: bool) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        if self.current_iface:
            switch.stp.set_bpduguard(self.current_iface, enabled)
        return ""

    def _cmd_stp_bpdufilter(self, tokens: list[str], enabled: bool) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        if self.current_iface:
            switch.stp.set_bpdufilter(self.current_iface, enabled)
        return ""

    def _cmd_stp_guard(self, tokens: list[str], guard: str) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        if self.current_iface:
            switch.stp.set_guard(self.current_iface, guard)
        return ""

    def _cmd_stp_port_cost(self, tokens: list[str]) -> str:
        # tokens: ['spanning-tree', 'cost', '<value>']
        if len(tokens) < 3:
            return "% Incomplete command."
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        try:
            cost = int(tokens[2])
        except ValueError:
            return f"% Invalid cost: {tokens[2]!r}"
        for vlan_id in switch.vlans:
            if self.current_iface:
                switch.stp.set_port_cost(self.current_iface, vlan_id, cost)
        return ""

    def _cmd_stp_port_priority_iface(self, tokens: list[str]) -> str:
        # tokens: ['spanning-tree', 'port-priority', '<value>']
        if len(tokens) < 3:
            return "% Incomplete command."
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        try:
            priority = int(tokens[2])
        except ValueError:
            return f"% Invalid priority: {tokens[2]!r}"
        for vlan_id in switch.vlans:
            if self.current_iface:
                switch.stp.set_port_priority(self.current_iface, vlan_id, priority)
        return ""

    def _cmd_stp_iface_vlan(self, tokens: list[str]) -> str:
        # tokens: ['spanning-tree', 'vlan', '<id>', 'cost|port-priority', '<val>']
        if len(tokens) < 5:
            return "% Incomplete command."
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        try:
            vlan_id = int(tokens[2])
        except ValueError:
            return f"% Invalid VLAN ID: {tokens[2]!r}"
        sub = tokens[3].lower()
        if sub == "cost":
            try:
                switch.stp.set_port_cost(self.current_iface or "", vlan_id, int(tokens[4]))
            except ValueError as exc:
                return f"% {exc}"
        elif sub == "port-priority":
            try:
                switch.stp.set_port_priority(self.current_iface or "", vlan_id, int(tokens[4]))
            except ValueError as exc:
                return f"% {exc}"
        return ""

    # ── Global STP commands ────────────────────────────────────────────────────

    def _cmd_stp_mode(self, tokens: list[str], mode_str: str) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree mode is only available on switch devices."
        from simulator_core.stp import STPMode
        mode_map = {
            "pvst": STPMode.PVST,
            "rapid-pvst": STPMode.RAPID_PVST,
            "mst": STPMode.MST,
        }
        switch.stp.mode = mode_map.get(mode_str, STPMode.RAPID_PVST)
        return ""

    def _cmd_stp_global_vlan(self, tokens: list[str]) -> str:
        """
        spanning-tree vlan <id> priority <value>
        spanning-tree vlan <id> root primary|secondary
        spanning-tree vlan <id> hello-time|forward-time|max-age <value>
        """
        if len(tokens) < 4:
            return "% Incomplete command."
        switch = self._get_switch()
        if switch is None:
            return "% spanning-tree commands only on switch devices."
        try:
            vlan_id = int(tokens[2])
        except ValueError:
            return f"% Invalid VLAN ID: {tokens[2]!r}"
        sub = tokens[3].lower()
        if sub == "priority":
            if len(tokens) < 5:
                return "% Incomplete command."
            try:
                priority = int(tokens[4])
                switch.stp.set_bridge_priority(vlan_id, priority)
            except ValueError as exc:
                return f"% {exc}"
        elif sub == "root":
            if len(tokens) < 5:
                return "% Incomplete command."
            level = tokens[4].lower()
            if level == "primary":
                try:
                    switch.stp.set_root_primary(vlan_id)
                except ValueError as exc:
                    return f"% {exc}"
            elif level == "secondary":
                switch.stp.set_root_secondary(vlan_id)
            else:
                return f"% Unknown root option: {level!r}"
        elif sub in ("hello-time", "forward-time", "max-age"):
            if len(tokens) < 5:
                return "% Incomplete command."
            try:
                val = int(tokens[4])
            except ValueError:
                return f"% Invalid value: {tokens[4]!r}"
            inst = switch.stp.get_instance(vlan_id)
            if inst:
                if sub == "hello-time":
                    inst.timers.hello_time = val
                elif sub == "forward-time":
                    inst.timers.forward_delay = val
                elif sub == "max-age":
                    inst.timers.max_age = val
        else:
            return f"% Unknown spanning-tree vlan option: {sub!r}"
        return ""

    def _cmd_stp_portfast_default(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch:
            switch.stp._portfast_default = True
        return ""

    def _cmd_stp_bpduguard_default(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch:
            # Apply bpduguard to all current portfast ports
            for inst in switch.stp.all_instances():
                for port in inst.port_states.values():
                    if port.portfast:
                        port.bpduguard = True
        return ""

    # ── EtherChannel commands ──────────────────────────────────────────────────

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

    # ── Show STP ──────────────────────────────────────────────────────────────

    def _cmd_show_stp_vlan(self, tokens: list[str], vlan_id: Optional[int]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show spanning-tree is only available on switch devices."
        return switch.stp.show_spanning_tree(vlan_id, active_ports=self._stp_up_ports())

    def _stp_up_ports(self) -> set[str]:
        """Switch ports that are up (IOS lists only these in STP output)."""
        device = self.simulation.topology.devices[self.device_id]
        return {
            n for n, i in device.interfaces.items()
            if i.is_physical_switchport and i.oper_state == InterfaceState.UP
        }

    def _cmd_show_stp_vlan_dispatch(self, tokens: list[str]) -> str:
        """show spanning-tree vlan <id>"""
        # tokens: ['show', 'spanning-tree', 'vlan', '<id>']
        if len(tokens) < 4:
            return "% Incomplete command."
        try:
            vlan_id = int(tokens[3])
        except ValueError:
            return f"% Invalid VLAN ID: {tokens[3]!r}"
        return self._cmd_show_stp_vlan(tokens, vlan_id)

    def _cmd_show_stp_summary(self, tokens: list[str]) -> str:
        switch = self._get_switch()
        if switch is None:
            return "% show spanning-tree is only available on switch devices."
        return switch.stp.show_spanning_tree_brief(active_ports=self._stp_up_ports())

    # ── Show interfaces trunk / status ────────────────────────────────────────

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

    def _cmd_show_interfaces_status(self, tokens: list[str]) -> str:
        """show interfaces status — brief port status table with speed/type."""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        from simulator_core.types import InterfaceState
        from simulator_core.port_types import detect_port_type, format_speed

        lines = [
            "Port      Name               Status       Vlan       Duplex  Speed Type",
        ]
        for name in _display_order(device):
            iface = device.interfaces[name]
            if not iface.is_physical_switchport:
                continue
            status = _switch_port_status(iface)
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

    # ── Show EtherChannel ─────────────────────────────────────────────────────

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

    # ── VLAN list formatter ────────────────────────────────────────────────────

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

    # ── User accounts ────────────────────────────────────────────────────────

    def _get_config(self):
        """Return the DeviceConfig for this session's device."""
        device = self.simulation.topology.devices.get(self.device_id)
        return device.config if device else None

    def _cmd_username(self, tokens: list[str]) -> str:
        # tokens: ['username', '<name>', 'privilege', '<level>', 'secret', '<password>']
        # or simplified: ['username', '<name>', 'secret', '<password>']
        if len(tokens) < 2:
            return "% Incomplete command."
        config = self._get_config()
        if config is None:
            return "% Device not found."
        username = tokens[1]
        privilege = 1
        password = ""
        # Parse: privilege <level> secret <password>
        i = 2
        while i < len(tokens):
            if tokens[i].lower() == "privilege" and i + 1 < len(tokens):
                try:
                    privilege = int(tokens[i + 1])
                    if not (0 <= privilege <= 15):
                        return f"% Privilege level must be 0-15."
                except ValueError:
                    return f"% Invalid privilege level: {tokens[i + 1]!r}"
                i += 2
            elif tokens[i].lower() in ("secret", "password") and i + 1 < len(tokens):
                password = tokens[i + 1]
                i += 2
            else:
                i += 1
        if not password:
            return "% Incomplete command. Usage: username <name> [privilege <level>] secret <password>"
        config.add_user(username, password, privilege)
        return ""

    def _cmd_no_username(self, tokens: list[str]) -> str:
        if len(tokens) < 3:
            return "% Incomplete command."
        config = self._get_config()
        if config is None:
            return "% Device not found."
        username = tokens[2]
        if not config.remove_user(username):
            return f"% User {username!r} not found."
        return ""

    # ── Enable secret / password ──────────────────────────────────────────────

    def _cmd_enable_secret(self, tokens: list[str]) -> str:
        # tokens: ['enable', 'secret', '<password>']
        if len(tokens) < 3:
            return "% Incomplete command."
        config = self._get_config()
        if config:
            config.set_enable_secret(tokens[2])
        return ""

    def _cmd_no_enable_secret(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config:
            config.enable_secret_hash = None
            config.enable_auth_required = config.enable_password_hash is not None
        return ""

    def _cmd_enable_password(self, tokens: list[str]) -> str:
        if len(tokens) < 3:
            return "% Incomplete command."
        config = self._get_config()
        if config:
            config.set_enable_password(tokens[2])
        return ""

    def _cmd_no_enable_password(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config:
            config.enable_password_hash = None
            config.enable_auth_required = config.enable_secret_hash is not None
        return ""

    # ── Line config ───────────────────────────────────────────────────────────

    def _cmd_enter_line(self, tokens: list[str]) -> str:
        # tokens: ['line', '<console|vty|aux>', '<first>', '[last]']
        if len(tokens) < 3:
            return "% Incomplete command."
        config = self._get_config()
        if config is None:
            return "% Device not found."
        typed = tokens[1].lower()
        kinds = [k for k in ("console", "vty", "aux") if k.startswith(typed)]
        if len(kinds) != 1:
            return _invalid_at(" ".join(tokens[:2]), tokens[1])
        kind = kinds[0]
        if not tokens[2].isdigit() or (len(tokens) > 3 and not tokens[3].isdigit()):
            return _invalid_at(" ".join(tokens), tokens[2])
        first = int(tokens[2])
        last = int(tokens[3]) if len(tokens) > 3 else first
        if kind in ("console", "aux"):
            if first != 0 or last != 0:
                return _invalid_at(" ".join(tokens[:3]), tokens[2])
            self.mode = CLIMode.LINE_CONFIG
            self.current_line = f"{kind} 0"
            return ""
        if not (0 <= first <= last <= 15):
            return _invalid_at(" ".join(tokens), tokens[-1])
        self.mode = CLIMode.LINE_CONFIG
        self.current_line = f"vty {first} {last}" if last > first else f"vty {first}"
        return ""

    def _cmd_line_login(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        if "local" in [t.lower() for t in tokens]:
            for line in self._get_current_lines(config):
                line.login_local = True
                line.login = False
        else:
            for line in self._get_current_lines(config):
                line.login = True
                line.login_local = False
        return ""

    def _cmd_line_no_login(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        for line in self._get_current_lines(config):
            line.login = False
            line.login_local = False
        return ""

    def _cmd_line_password(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        for line in self._get_current_lines(config):
            line.set_password(tokens[1])
        return ""

    def _cmd_line_no_password(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        for line in self._get_current_lines(config):
            line.password_hash = None
        return ""

    def _cmd_line_exec_timeout(self, tokens: list[str]) -> str:
        # tokens: ['exec-timeout', '<minutes>', '[seconds]']
        if len(tokens) < 2:
            return "% Incomplete command."
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        try:
            minutes = int(tokens[1])
            seconds = int(tokens[2]) if len(tokens) > 2 else 0
        except ValueError:
            return "% Invalid timeout value."
        for line in self._get_current_lines(config):
            line.exec_timeout = minutes * 60 + seconds
        return ""

    def _cmd_line_no_exec_timeout(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        for line in self._get_current_lines(config):
            line.exec_timeout = 0  # 0 = never timeout
        return ""

    def _cmd_line_logging_sync(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        for line in self._get_current_lines(config):
            line.logging_synchronous = True
        return ""

    def _cmd_line_no_logging_sync(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        for line in self._get_current_lines(config):
            line.logging_synchronous = False
        return ""

    def _cmd_line_transport(self, tokens: list[str]) -> str:
        # tokens: ['transport', 'input', '<protocol>...']
        if len(tokens) < 3:
            return "% Incomplete command."
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        protocols = tokens[2:]
        for line in self._get_current_lines(config):
            line.transport_input = protocols
        return ""

    def _cmd_line_privilege(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        config = self._get_config()
        if config is None or self.current_line is None:
            return "% Not in line configuration mode."
        try:
            level = int(tokens[1])
            if not (0 <= level <= 15):
                return "% Privilege level must be 0-15."
        except ValueError:
            return "% Invalid privilege level."
        for line in self._get_current_lines(config):
            line.privilege = level
        return ""

    def _get_current_lines(self, config):
        """Return the LineConfig objects matching self.current_line."""
        from simulator_core.device_config import LineType
        if not self.current_line:
            return []
        parts = self.current_line.split()
        if parts[0] == "console":
            return [config.console_line]
        elif parts[0] == "vty":
            if len(parts) >= 3:
                first, last = int(parts[1]), int(parts[2])
            else:
                first = last = int(parts[1])
            return config.get_vty_range(first, last)
        elif parts[0] == "aux":
            return [config.aux_line]
        return []

    # ── Logging ───────────────────────────────────────────────────────────────

    def _cmd_logging(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None:
            return "% Device not found."
        if len(tokens) < 2:
            return "% Incomplete command."
        sub = tokens[1].lower()
        if sub == "buffered":
            # logging buffered [<size>] [<level>]
            if len(tokens) > 2:
                t2 = tokens[2]
                if t2.isdigit():
                    config.logging_buffered_size = int(t2)
                    if len(tokens) > 3:
                        try:
                            config.logging_buffered_level = __import__(
                                "simulator_core.device_config", fromlist=["LogSeverity"]
                            ).LogSeverity.from_name(tokens[3])
                        except ValueError:
                            return f"% Invalid log level: {tokens[3]!r}"
                else:
                    try:
                        config.logging_buffered_level = __import__(
                            "simulator_core.device_config", fromlist=["LogSeverity"]
                        ).LogSeverity.from_name(t2)
                    except ValueError:
                        return f"% Invalid log level: {t2!r}"
            config.logging_enabled = True
            return ""
        if sub == "console":
            if len(tokens) > 2:
                try:
                    config.logging_console_level = __import__(
                        "simulator_core.device_config", fromlist=["LogSeverity"]
                    ).LogSeverity.from_name(tokens[2])
                except ValueError:
                    return f"% Invalid log level: {tokens[2]!r}"
            return ""
        if sub == "synchronous":
            config.logging_enabled = True
            return ""
        if sub == "on":
            config.logging_enabled = True
            return ""
        # Assume it's a host IP for syslog
        config.logging_hosts.append(tokens[1])
        return ""

    def _cmd_no_logging(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None:
            return "% Device not found."
        if len(tokens) < 3:
            return "% Incomplete command."
        host = tokens[2]
        if host in config.logging_hosts:
            config.logging_hosts.remove(host)
        return ""

    # ── Service ──────────────────────────────────────────────────────────────

    def _cmd_service_password_encryption(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config:
            config.service_password_encryption = True
        return ""

    # ── Banner ────────────────────────────────────────────────────────────────

    def _cmd_banner(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        config = self._get_config()
        if config is None:
            return "% Device not found."
        banner_type = tokens[1].lower()
        # IOS: the first character after the banner type is the delimiter;
        # the banner is the text up to the next occurrence of it
        # ("banner motd #Authorized only#").  "^C" is accepted as a
        # two-character delimiter, as in running-config output.
        raw = " ".join(tokens[2:]).strip()
        if raw.startswith("^C"):
            body = raw[2:]
            text = body.split("^C", 1)[0]
        elif raw and not raw[0].isalnum():
            delim, body = raw[0], raw[1:]
            text = body.split(delim, 1)[0]
        elif raw:
            # No delimiter typed (IOS would wait for more lines); accept the
            # rest of the line as the banner text.
            text = raw
        else:
            text = ""
        text = text.strip()
        if banner_type == "motd":
            config.banner_motd = text
        elif banner_type == "login":
            config.banner_login = text
        elif banner_type == "exec":
            config.banner_exec = text
        else:
            return f"% Unknown banner type: {banner_type!r}"
        return ""

    # ── IP settings ───────────────────────────────────────────────────────────

    def _cmd_ip_domain_lookup(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config:
            config.no_ip_domain_lookup = False
        return ""

    def _cmd_no_ip_domain_lookup(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config:
            config.no_ip_domain_lookup = True
        return ""

    def _cmd_ip_domain_name(self, tokens: list[str]) -> str:
        if len(tokens) < 3:
            return "% Incomplete command."
        config = self._get_config()
        if config:
            config.ip_domain_name = tokens[2]
        return ""

    def _cmd_ip_default_gateway(self, tokens: list[str]) -> str:
        """ip default-gateway <ip-address>"""
        if len(tokens) < 3:
            return "% Incomplete command."
        from ipaddress import IPv4Address
        try:
            IPv4Address(tokens[2])
        except ValueError:
            return f"% Invalid IP address: {tokens[2]!r}"
        config = self._get_config()
        if config:
            config.ip_default_gateway = tokens[2]
        return ""

    def _cmd_no_ip_default_gateway(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config:
            config.ip_default_gateway = ""
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
            return "% Unrecognized host or address, or protocol not running."

        from simulator_core.exceptions import ConfigurationError
        pinger = None
        try:
            pinger = self.simulation.get_host(self.device_id)
        except KeyError:
            pinger = self._get_router() or self._get_switch()
        if pinger is None:
            return "% Ping is not supported on this device type."
        try:
            result = pinger.ping(target, count=repeat)
        except ConfigurationError as exc:
            return f"% {exc}"
        self.simulation.run()

        # One character per echo, in sequence order: '!' reply, '.' timeout.
        replied = {r.sequence for r in result.results if r.success}
        lines = [
            "\nType escape sequence to abort.",
            f"Sending {result.sent}, 100-byte ICMP Echos to {target}, timeout is 2 seconds:",
            "".join("!" if seq in replied else "." for seq in range(result.sent)),
        ]
        pct = int(result.received / result.sent * 100) if result.sent else 0
        summary = f"Success rate is {pct} percent ({result.received}/{result.sent})"
        if result.received:
            rtts = [r.rtt_ticks for r in result.results if r.success and r.rtt_ticks is not None]
            if rtts:
                summary += f", round-trip min/avg/max = {min(rtts)}/{sum(rtts)//len(rtts)}/{max(rtts)} ticks"
        lines.append(summary)
        if result.received == 0:
            reason = next(
                (r.drop_reason for r in result.results if r.drop_reason), None
            )
            from simulator_core.devices.router import DROP_ARP_PENDING
            if reason == DROP_ARP_PENDING:
                # The ARP request was never answered, so nothing was sent.
                reason = ("no ARP reply from the next hop - check its address, "
                          "cabling and that its interface is up")
            if reason:
                lines.append(f"% {reason}")
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

    def _show_running_iface_dispatch(self, tokens: list[str]) -> str:
        """Dispatch 'show running-config interface <name>' with fuzzy match."""
        # tokens: ['show', 'running-config', 'interface', '<name>']
        tokens = _join_iface_tokens(tokens, 3)
        if len(tokens) < 4:
            return "% Incomplete command."
        iface_name = tokens[3]
        device = self.simulation.topology.devices.get(self.device_id)
        if device:
            matches = _match_iface(iface_name, list(device.interfaces.keys()))
            if len(matches) == 1:
                return self._cmd_show_running_iface(tokens, matches[0])
        return f"% Interface {iface_name!r} not found."

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

    def _cmd_show_ip_route(self, tokens: list[str]) -> str:
        """
        show ip route [static | connected | <address>]

        IOS layout: L (local /32) routes alongside each connected network,
        classful "is subnetted" / "is variably subnetted" headers, entries in
        address order, full interface names.
        """
        try:
            router = self.simulation.get_router(self.device_id)
        except KeyError:
            return "% show ip route is only available on router devices."
        from ipaddress import IPv4Address as _Addr, IPv4Network as _Net
        from simulator_core.routing import RouteSource

        device = self.simulation.topology.devices[self.device_id]
        args = tokens[3:]
        rt = router.routing_table

        if args and args[0][:1].isdigit():
            try:
                return self._show_ip_route_entry(rt, _Addr(args[0]))
            except ValueError:
                return _invalid_at(" ".join(tokens[:4]), args[0])

        # (network, code, description) for every displayed route
        entries: list[tuple] = []
        for r in rt.routes:
            if r.source == RouteSource.CONNECTED:
                iface = device.interfaces.get(r.outgoing_interface)
                long = _long_name(r.outgoing_interface)
                entries.append((r.network, "C", f"is directly connected, {long}"))
                if iface is not None and iface.ip_config is not None:
                    entries.append((_Net(f"{iface.ip_config.address}/32"), "L",
                                    f"is directly connected, {long}"))
            elif r.source == RouteSource.STATIC:
                code = "S*" if r.network.prefixlen == 0 else "S"
                if r.next_hop is None:
                    desc = f"is directly connected, {_long_name(r.outgoing_interface)}"
                elif r.exit_interface:
                    desc = f"[1/0] via {r.next_hop}, {_long_name(r.exit_interface)}"
                else:
                    desc = f"[1/0] via {r.next_hop}"
                entries.append((r.network, code, desc))

        if args:
            word = args[0].lower()
            if "static".startswith(word):
                entries = [e for e in entries if e[1].startswith("S")]
            elif "connected".startswith(word):
                entries = [e for e in entries if e[1] in ("C", "L")]
            else:
                return _invalid_at(" ".join(tokens[:4]), args[0])

        default = next((r for r in rt.routes if r.network.prefixlen == 0), None)
        if default is not None and default.next_hop is not None:
            gw_line = f"Gateway of last resort is {default.next_hop} to network 0.0.0.0"
        elif default is not None:
            gw_line = "Gateway of last resort is 0.0.0.0 to network 0.0.0.0"
        else:
            gw_line = "Gateway of last resort is not set"
        lines = [
            "Codes: L - local, C - connected, S - static, * - candidate default",
            "",
            gw_line,
            "",
        ]

        def classful(net) -> Optional[int]:
            first = int(net.network_address) >> 24
            return 8 if first < 128 else 16 if first < 192 else 24 if first < 224 else None

        groups: dict = {}
        for net, code, desc in sorted(entries, key=lambda e: (int(e[0].network_address), e[0].prefixlen)):
            bits = classful(net)
            if bits is None or net.prefixlen < bits:
                groups.setdefault((net, None), []).append((net, code, desc))
            else:
                major = _Net(f"{net.network_address}/{bits}", strict=False)
                groups.setdefault((major, bits), []).append((net, code, desc))

        for (key, bits), items in sorted(groups.items(), key=lambda kv: int(kv[0][0].network_address)):
            subnetted = bits is not None and any(n.prefixlen > bits for n, _, _ in items)
            if subnetted:
                masks = {n.prefixlen for n, _, _ in items}
                if len(masks) == 1:
                    lines.append(f"      {key.network_address}/{masks.pop()} is subnetted, {len(items)} subnets")
                else:
                    lines.append(f"      {key} is variably subnetted, {len(items)} subnets, {len(masks)} masks")
                for net, code, desc in items:
                    lines.append(f"{code:<9}{net} {desc}")
            else:
                for net, code, desc in items:
                    lines.append(f"{code:<6}{net} {desc}")
        return "\n".join(lines)

    def _show_ip_route_entry(self, rt, address) -> str:
        """show ip route <address>: the best matching route in detail."""
        from simulator_core.routing import RouteSource
        route = rt.lookup(address)
        if route is None:
            return "% Network not in table"
        lines = [f"Routing entry for {route.network}"]
        if route.source == RouteSource.CONNECTED:
            lines += [
                '  Known via "connected", distance 0, metric 0 (connected, via interface)',
                "  Routing Descriptor Blocks:",
                f"  * directly connected, via {_long_name(route.outgoing_interface)}",
                "      Route metric is 0, traffic share count is 1",
            ]
        else:
            via = (f"  * {route.next_hop}" if route.next_hop is not None
                   else f"  * directly connected, via {_long_name(route.outgoing_interface)}")
            lines += [
                '  Known via "static", distance 1, metric 0',
                "  Routing Descriptor Blocks:",
                via,
                "      Route metric is 0, traffic share count is 1",
            ]
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
            vname = lambda v: switch.vlans.get(v) or ("default" if v == 1 else f"VLAN{v:04d}")  # noqa: E731
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
            header += f" ({_switch_port_status(iface)})"
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

    def _cmd_show_arp(self, tokens: list[str]) -> str:
        router = self._get_router()
        if router is not None:
            return self._show_router_arp(router.arp_cache)
        switch = self._get_switch()
        if switch is not None:
            return self._show_router_arp(switch.mgmt_arp_cache)
        try:
            host = self.simulation.get_host(self.device_id)
        except KeyError:
            return "% show arp is not supported on this device."

        cache = host.arp_cache
        lines = ["Protocol  Address          Age (min)  Hardware Addr         Type   Interface"]
        if not cache:
            lines.append("(ARP cache is empty)")
        else:
            iface_name = list(self.simulation.topology.devices[self.device_id].interfaces.keys())[0]
            for ip, mac in cache.items():
                lines.append(f"Internet  {str(ip):<16} -          {_cisco_mac(mac)}   ARPA   {iface_name}")
        return "\n".join(lines)

    def _show_router_arp(self, arp_cache: dict) -> str:
        """
        IOS-style router ARP table: the router's own interface addresses
        (age "-") followed by learned neighbours, each on the interface
        whose connected subnet contains it.
        """
        device = self.simulation.topology.devices[self.device_id]
        router = self._get_router()
        rows = []
        own_ips = set()
        for name, iface in device.interfaces.items():
            if (iface.ip_config and iface.admin_state == InterfaceState.UP
                    and iface.oper_state == InterfaceState.UP):
                own_ips.add(iface.ip_config.address)
                rows.append((iface.ip_config.address, "-", iface.mac, name))
        for ip, mac in arp_cache.items():
            if ip in own_ips:
                continue
            iface_name = next(
                (n for n, i in device.interfaces.items()
                 if i.ip_config and ip in i.ip_config.network),
                None,
            )
            if iface_name is None and router is not None:
                # Learned by proxy ARP / exit-interface routing
                route = router.routing_table.lookup(ip)
                iface_name = route.outgoing_interface if route else ""
            rows.append((ip, "0", mac, iface_name or ""))
        lines = ["Protocol  Address          Age (min)  Hardware Addr   Type   Interface"]
        for ip, age, mac, name in sorted(rows, key=lambda r: int(r[0])):
            lines.append(
                f"Internet  {str(ip):<16} {age:>9}   {_cisco_mac(mac)}  ARPA   {_long_name(name)}"
            )
        return "\n".join(lines)

    def _cmd_show_mac(self, tokens: list[str]) -> str:
        """show mac address-table [dynamic | vlan <id> | interface <name>]"""
        try:
            switch = self.simulation.get_switch(self.device_id)
        except KeyError:
            return "% show mac address-table is only supported on switch devices."
        device = self.simulation.topology.devices[self.device_id]
        entries = sorted(
            ((vlan, mac, port) for (mac, vlan), port in switch.mac_table.items()),
            key=lambda e: (e[0], _natural_key(e[2]), e[1]),
        )
        args = [a.lower() for a in tokens[3:]]
        if args:
            if "dynamic".startswith(args[0]):
                pass
            elif "vlan".startswith(args[0]) and len(args) > 1 and args[1].isdigit():
                entries = [e for e in entries if e[0] == int(args[1])]
            elif "interface".startswith(args[0]) and len(args) > 1:
                joined = _join_iface_tokens(tokens[3:], 1)
                found = _match_iface(joined[1], list(device.interfaces))
                if len(found) != 1:
                    return _invalid_at(" ".join(tokens[:5]), tokens[4])
                entries = [e for e in entries if e[2] == found[0]]
            else:
                return _invalid_at(" ".join(tokens[:4]), tokens[3])
        lines = [
            "          Mac Address Table",
            "-------------------------------------------",
            "",
            "Vlan    Mac Address       Type        Ports",
            "----    -----------       --------    -----",
        ]
        for vlan, mac, port in entries:
            lines.append(f"{vlan:>4}    {_cisco_mac(mac)}    DYNAMIC     {port}")
        lines.append(f"Total Mac Addresses for this criterion: {len(entries)}")
        return "\n".join(lines)

    # ── CDP show / config commands ─────────────────────────────────────────────

    def _get_cdp_manager(self):
        """Return the CDPManager for this session's device, or None."""
        sim = self.simulation
        try:
            return sim.get_switch(self.device_id).cdp_manager
        except KeyError:
            pass
        try:
            return sim.get_router(self.device_id).cdp_manager
        except KeyError:
            pass
        try:
            return sim.get_host(self.device_id).cdp_manager
        except KeyError:
            pass
        return None

    def _cmd_show_cdp(self, tokens: list[str]) -> str:
        """show cdp — global CDP status."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        status = "enabled" if mgr.is_enabled else "disabled"
        return (
            f"Global CDP information:\n"
            f"        Sending CDP packets every {mgr.hello_interval} seconds\n"
            f"        Sending a holdtime value of {mgr.holdtime} seconds\n"
            f"        Sending CDPv2 advertisements is enabled\n"
            f"        CDP is {status}"
        )

    def _cmd_show_cdp_neighbors(self, tokens: list[str]) -> str:
        """show cdp neighbors — Cisco-style brief neighbor table."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        if not mgr.is_enabled:
            return "% CDP is disabled."
        neighbors = mgr.get_neighbors()
        lines = [
            "Capability Codes: R - Router, T - Trans Bridge, B - Source Route Bridge",
            "                  S - Switch, H - Host, I - IGMP, r - Repeater, P - Phone",
            "",
            f"{'Device ID':<16} {'Local Intrfce':<17} {'Holdtme':<10} {'Capability':<11} {'Platform':<18} {'Port ID'}",
        ]
        if not neighbors:
            lines.append("")
            lines.append("Total cdp entries displayed : 0")
            return "\n".join(lines)
        for local_iface, entry in sorted(neighbors):
            # Capability abbreviation
            cap_abbr = {"Switch": "S", "Router": "R", "Host": "H"}.get(entry.capabilities, "?")
            lines.append(
                f"{entry.device_id:<16} {local_iface:<17} {entry.holdtime:<10} {cap_abbr:<11} {entry.platform:<18} {entry.local_interface}"
            )
        lines.append("")
        lines.append(f"Total cdp entries displayed : {len(neighbors)}")
        return "\n".join(lines)

    def _cmd_show_cdp_neighbors_detail(self, tokens: list[str]) -> str:
        """show cdp neighbors detail — full CDP neighbor information."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        if not mgr.is_enabled:
            return "% CDP is disabled."
        neighbors = mgr.get_neighbors()
        if not neighbors:
            return "% No CDP neighbor entries found."
        blocks = []
        for local_iface, entry in sorted(neighbors):
            ip_str = ", ".join(entry.ip_addresses) if entry.ip_addresses else "(none)"
            block = (
                f"-------------------------\n"
                f"Device ID: {entry.device_id}\n"
                f"Entry address(es):\n"
                f"  IP address: {ip_str}\n"
                f"Platform: {entry.platform},  Capabilities: {entry.capabilities}\n"
                f"Interface: {local_iface},  Port ID (outgoing port): {entry.local_interface}\n"
                f"Holdtime : {entry.holdtime} sec\n"
                f"\n"
                f"Version :\n"
                f"{entry.software_version}\n"
                f"\n"
                f"advertisement version: {entry.advertisement_version}\n"
                f"Duplex: {entry.duplex}\n"
                f"Native VLAN: {entry.native_vlan}\n"
                f"VTP Management Domain: '{entry.vtp_domain}'"
            )
            blocks.append(block)
        return "\n".join(blocks)

    def _cmd_show_cdp_interface(self, tokens: list[str]) -> str:
        """show cdp interface — per-interface CDP status."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        device = self.simulation.topology.devices.get(self.device_id)
        if device is None:
            return "% Device not found."
        lines = []
        for iface_name, iface in device.interfaces.items():
            if iface.is_svi or iface.is_loopback:
                continue
            cdp_iface_enabled = getattr(iface, "_cdp_enabled", True)
            status = "Sending and receiving CDP packets." if (mgr.is_enabled and cdp_iface_enabled) else "CDP disabled on this interface."
            lines.append(f"{iface_name} is up, line protocol is up")
            lines.append(f"  Encapsulation ARPA")
            lines.append(f"  Sending CDP packets every {mgr.hello_interval} seconds")
            lines.append(f"  Holdtime is {mgr.holdtime} seconds")
            lines.append(f"  {status}")
            lines.append("")
        if not lines:
            return "% No physical interfaces found."
        return "\n".join(lines)

    # ── CDP config commands ───────────────────────────────────────────────────

    def _cmd_cdp_run(self, tokens: list[str], enabled: bool) -> str:
        """cdp run / no cdp run — enable/disable CDP globally."""
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        mgr.is_enabled = enabled
        return ""

    def _cmd_cdp_timer(self, tokens: list[str]) -> str:
        """cdp timer <seconds> — set CDP hello interval."""
        # tokens: ['cdp', 'timer', '<seconds>']
        if len(tokens) < 3:
            return "% Incomplete command.\nUsage: cdp timer <seconds>"
        try:
            val = int(tokens[2])
            if not (5 <= val <= 900):
                return "% CDP timer must be between 5 and 900 seconds."
        except ValueError:
            return f"% Invalid value: {tokens[2]!r}"
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        mgr.hello_interval = val
        return ""

    def _cmd_cdp_holdtime(self, tokens: list[str]) -> str:
        """cdp holdtime <seconds> — set CDP holdtime."""
        # tokens: ['cdp', 'holdtime', '<seconds>']
        if len(tokens) < 3:
            return "% Incomplete command.\nUsage: cdp holdtime <seconds>"
        try:
            val = int(tokens[2])
            if not (10 <= val <= 255):
                return "% CDP holdtime must be between 10 and 255 seconds."
        except ValueError:
            return f"% Invalid value: {tokens[2]!r}"
        mgr = self._get_cdp_manager()
        if mgr is None:
            return "% CDP is not available on this device."
        mgr.holdtime = val
        return ""

    def _cmd_cdp_iface_enable(self, tokens: list[str], enabled: bool) -> str:
        """cdp enable / no cdp enable — enable/disable CDP on the current interface."""
        iface = self._get_current_iface()
        if iface is None:
            return "% No interface selected."
        iface._cdp_enabled = enabled  # type: ignore[attr-defined]
        return ""

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
        ]
        # Device-level config lines (users, lines, logging, etc.)
        lines += device.config.show_running_config_lines()
        lines += [
            "!",
            f"hostname {device.hostname}",
            "!",
        ]
        switch = self._get_switch()
        if switch is not None:
            lines += _stp_global_lines(switch.stp)
            lines.append("!")
        for name, iface in device.interfaces.items():
            # Skip SVIs on devices that don't support them (e.g. L2-only switches).
            # They should not exist — but if one was created before the capability
            # check was enforced, exclude it from the running-config.
            if iface.is_svi and not device.supports_svi:
                continue
            lines.append("!")
            lines += _iface_config_lines(device, name, iface, switch.stp if switch else None)
        router = self._get_router()
        if router is not None and router.routing_table.static_routes:
            lines.append("!")
            for r in router.routing_table.static_routes:
                target = " ".join(
                    part for part in (
                        _long_name(r.exit_interface) if r.exit_interface else "",
                        str(r.next_hop) if r.next_hop is not None else "",
                    ) if part
                )
                lines.append(f"ip route {r.network.network_address} {r.network.netmask} {target}")
        lines += ["!", "end"]
        return "\n".join(lines)

    def _cmd_show_running_iface(self, tokens: list[str], iface_name: str) -> str:
        """show running-config interface <name>"""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        # Support abbreviations — try to match the name
        iface_names = list(device.interfaces.keys())
        matches = _match_iface(iface_name, iface_names)
        if not matches:
            return f"% Interface {iface_name!r} not found."
        iface = device.interfaces.get(matches[0])
        if not iface:
            return f"% Interface {matches[0]!r} not found."
        from simulator_core.types import InterfaceState
        from ipaddress import IPv4Network as _Net
        lines = [
            "Building configuration...\n",
            "Current configuration:",
            "!",
        ]
        switch = self._get_switch()
        lines += _iface_config_lines(device, matches[0], iface, switch.stp if switch else None)
        lines += ["end"]
        return "\n".join(lines)

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

    def _cmd_show_logging(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None:
            return "% Device not found."
        lines = [
            "Syslog logging: enabled (" + config.logging_console_level.name.lower() + ")",
            f"Logging buffer size: {config.logging_buffered_size}",
            f"Logging hosts: {', '.join(config.logging_hosts) or 'none'}",
            f"Facility: {config.logging_facility}",
            "",
            "Log Buffer:",
        ]
        if not config.log_buffer:
            lines.append("(empty)")
        else:
            for entry in config.log_buffer[-20:]:  # last 20 entries
                lines.append(str(entry))
        return "\n".join(lines)

    def _cmd_show_users(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config is None:
            return "% Device not found."
        lines = [
            "Line       User       Host(s)         Idle     Location",
            "----       ----       -------         ----     --------",
            "con 0      ---        ---              00:00:00 (current session)",
        ]
        for vty in config.vty_lines:
            lines.append(f"vty {vty.line_num}     ---        ---              ---     ---")
        lines.append("\nConfigured users:")
        if not config.users:
            lines.append("(no local users configured)")
        else:
            for username, user in config.users.items():
                lines.append(f"  {username} (privilege {user.privilege})")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interface name matching
# ---------------------------------------------------------------------------

# Full IOS type keyword for each interface-name type prefix used by the
# device catalog.  A user-typed type is accepted when it is a prefix of the
# full keyword ("f", "fa", "fast", "FastEthernet" all select "Fa" ports).
_IFACE_TYPE_FULL = {
    "fa": "fastethernet",
    "gi": "gigabitethernet",
    "te": "tengigabitethernet",
    "eth": "ethernet",
    "e": "ethernet",
    "se": "serial",
    "po": "port-channel",
    "loopback": "loopback",
    "vlan": "vlan",
}

_IFACE_NAME_RE = re.compile(r"^([A-Za-z][A-Za-z-]*)\s*(\d[\d/.:]*)$")


def _stp_global_lines(stp) -> list[str]:
    """Global spanning-tree lines of the running-config, in IOS order."""
    lines = [f"spanning-tree mode {stp.mode.value}", "spanning-tree extend system-id"]
    if getattr(stp, "_portfast_default", False):
        lines.append("spanning-tree portfast default")
    for vlan_id, priority in stp.configured_priorities().items():
        lines.append(f"spanning-tree vlan {vlan_id} priority {priority}")
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


def _iface_config_lines(device, name: str, iface, stp=None) -> list[str]:
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
                allowed = CLISession._format_vlan_list(sorted(iface.trunk_allowed_vlans))
                lines.append(f" switchport trunk allowed vlan {allowed}")
        if mode == "trunk":
            lines.append(" switchport mode trunk")
        elif mode.startswith("dynamic_"):
            lines.append(f" switchport mode dynamic {mode[len('dynamic_'):]}")
        elif mode == "access" and (iface.vlan != 1 or iface.dtp_nonegotiate):
            lines.append(" switchport mode access")
        if iface.dtp_nonegotiate:
            lines.append(" switchport nonegotiate")
    if is_switchport and stp is not None:
        lines += _stp_iface_lines(stp, name)
    if iface.admin_state == InterfaceState.DOWN:
        lines.append(" shutdown")
    lines.append("!")
    return lines


def _dtp_mode_word(iface) -> str:
    """The Mode column of ``show interfaces trunk``."""
    if iface.switchport_mode == "dynamic_desirable":
        return "desirable"
    if iface.switchport_mode == "dynamic_auto":
        return "auto"
    return "nonegotiate" if iface.dtp_nonegotiate else "on"


def _mask_prefix(mask_int: int) -> Optional[int]:
    """Prefix length of a contiguous dotted mask, or None if non-contiguous."""
    inverted = (~mask_int) & 0xFFFFFFFF
    if inverted & (inverted + 1):
        return None
    return 32 - inverted.bit_length()


def _is_valid_host_address(ip: IPv4Address) -> bool:
    """IOS rejects loopback, 0.x, multicast and class E as interface addresses."""
    first = int(ip) >> 24
    return not (first == 0 or first == 127 or first >= 224)


from simulator_core.naming import LONG_IFACE_TYPE as _LONG_IFACE_TYPE  # noqa: E402
from simulator_core.naming import long_name as _long_name  # noqa: E402,F401


def _display_order(device) -> list[str]:
    """
    IOS listing order: physical ports in hardware order, each followed by
    its subinterfaces, then loopbacks and SVIs in numeric order.
    """
    names = list(device.interfaces)
    physical = [n for n in names if "." not in n
                and not n.lower().startswith(("vlan", "loopback"))]
    order: list[str] = []
    for n in physical:
        order.append(n)
        subs = [s for s in names if s.startswith(n + ".")]
        order += sorted(subs, key=lambda x: int(x.rsplit(".", 1)[1]))
    rest = [n for n in names if n not in order]
    order += sorted(rest, key=_natural_key)
    return order


def _natural_key(name: str) -> tuple:
    """Sort Fa0/2 before Fa0/10."""
    return tuple(int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name))


def _hardware_name(name: str) -> str:
    low = name.lower()
    for prefix, hw in (("fa", "Fast Ethernet"), ("gi", "Gigabit Ethernet"),
                       ("te", "Ten Gigabit Ethernet"), ("vlan", "EtherSVI"),
                       ("loopback", "Loopback"), ("po", "EtherChannel")):
        if low.startswith(prefix):
            return hw
    return "Ethernet"


def _media_type(name: str) -> str:
    low = name.lower()
    if low.startswith("gi"):
        return "10/100/1000BaseTX"
    if low.startswith("te"):
        return "10GBase-SR"
    return "10/100BaseTX"


def _switch_port_status(iface) -> str:
    """show interfaces status word: connected / notconnect / disabled."""
    if iface.admin_state == InterfaceState.DOWN:
        return "disabled"
    if iface.oper_state == InterfaceState.UP:
        return "connected"
    return "notconnect"


def _cisco_mac(mac) -> str:
    """Cisco dotted MAC notation: ``aa:bb:cc:dd:ee:ff`` → ``aabb.ccdd.eeff``."""
    raw = str(getattr(mac, "value", mac)).replace(":", "").replace("-", "").replace(".", "").lower()
    if len(raw) != 12:
        return str(mac)
    return f"{raw[0:4]}.{raw[4:8]}.{raw[8:12]}"


def _virtual_iface_mac(device_id: str, iface_name: str):
    """
    Stable MAC for an interface created from the CLI (SVI, loopback,
    subinterface).  Derived from a digest so a replayed lab gets the same
    address in every process (Python's hash() is randomised per process).
    """
    import hashlib
    import random
    from simulator_core.addresses import MACAddress
    seed = int(hashlib.md5(f"{device_id}/{iface_name}".encode()).hexdigest(), 16) % (2 ** 31)
    return MACAddress.generate(random.Random(seed))


def _split_iface_name(name: str) -> Optional[tuple[str, str]]:
    """Split ``"Fa0/1"`` into ``("fa", "0/1")``; None if not type+number."""
    m = _IFACE_NAME_RE.match(name.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2)


def _match_iface(input_name: str, iface_names: list[str]) -> list[str]:
    """
    Match a user-typed interface name against the device's interfaces.

    IOS rules: the interface *type* may be abbreviated to any unambiguous
    prefix of its full keyword, but the *number* must match exactly.

    - ``fa0/1``, ``f0/1``, ``FastEthernet0/1`` → ``Fa0/1``
    - ``g0/1`` on a FastEthernet-only switch → no match (wrong type)
    - ``fa0/1.10`` → no match (subinterfaces are not modelled)
    - ``0/1`` → no match (a type is required)

    Returns every matching interface name; more than one means the typed
    type prefix is ambiguous on this device.
    """
    lower_input = input_name.strip().lower()

    exact = [n for n in iface_names if n.lower() == lower_input]
    if exact:
        return exact

    parsed = _split_iface_name(input_name)
    if parsed is None:
        return []
    typed_type, typed_number = parsed

    matches = []
    for name in iface_names:
        own = _split_iface_name(name)
        if own is None:
            continue
        own_type, own_number = own
        if own_number != typed_number:
            continue
        full_type = _IFACE_TYPE_FULL.get(own_type, own_type)
        if typed_type == own_type or full_type.startswith(typed_type):
            matches.append(name)
    return matches


def _join_iface_tokens(tokens: list[str], idx: int) -> list[str]:
    """
    Collapse IOS's spaced interface form (``FastEthernet 0/1``) at
    ``tokens[idx]`` into a single token (``FastEthernet0/1``).
    """
    if (len(tokens) > idx + 1 and tokens[idx].isalpha()
            and tokens[idx + 1][:1].isdigit()):
        return tokens[:idx] + [tokens[idx] + tokens[idx + 1]] + tokens[idx + 2:]
    return tokens


def _expand_iface_range(spec: str, iface_names: list[str]) -> tuple[list[str], Optional[str]]:
    """
    Expand an ``interface range`` specification into interface names.

    Accepts comma-separated segments, each ``<type><slot>/<first>[ - <last>]``,
    e.g. ``fa0/1 - 5``, ``fa0/1-5``, ``f0/1 - 2 , f0/5``.

    Returns (names, None) on success or ([], error-message) on failure.
    """
    seg_re = re.compile(
        r"^([A-Za-z][A-Za-z-]*)\s*((?:\d+/)*)(\d+)\s*(?:-\s*(\d+))?$"
    )
    result: list[str] = []
    for segment in spec.split(","):
        segment = segment.strip()
        m = seg_re.match(segment)
        if not m:
            return [], f"% Invalid interface range: {segment!r}"
        typ, slot, first, last = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        last_i = int(last) if last is not None else first
        if last_i < first:
            return [], f"% Invalid interface range: {segment!r}"
        for port in range(first, last_i + 1):
            typed = f"{typ}{slot}{port}"
            found = _match_iface(typed, iface_names)
            if len(found) != 1:
                return [], f"% Invalid interface name: {typed!r}"
            if found[0] not in result:
                result.append(found[0])
    return result, None


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


_INVALID_HEADER = "% Invalid input detected at '^' marker."
# _invalid/_invalid_at return the header followed by a machine-readable
# marker (typed prefix + offending token).  CLISession.execute() replaces it
# with IOS layout: a caret under the offending token, aligned with the
# prompt line, then the header.
_INVALID_MARK = re.compile(re.escape(_INVALID_HEADER) + "\x00([^\x00]*)\x00([^\x01]*)\x01")


def _invalid(tok: str) -> str:
    return f"{_INVALID_HEADER}\x00{tok}\x00{tok}\x01"


def _invalid_at(line: str, bad_tok: str) -> str:
    return f"{_INVALID_HEADER}\x00{line}\x00{bad_tok}\x01"


def _render_invalid(output: str, raw: str, prompt: str) -> str:
    """
    IOS error layout::

        Switch#shwo version
               ^
        % Invalid input detected at '^' marker.

    The caret sits under the offending token of the line as typed.
    """
    if "\x00" not in output:
        return output
    typed = raw.split("|", 1)[0]
    starts = [m.start() for m in re.finditer(r"\S+", typed)]

    def repl(m: re.Match) -> str:
        parts = m.group(1).split()
        bad = m.group(2).lower()
        idx = max((i for i, t in enumerate(parts) if t.lower() == bad), default=len(parts) - 1)
        col = starts[idx] if 0 <= idx < len(starts) else len(typed.rstrip())
        return " " * (len(prompt) + col) + "^\n" + _INVALID_HEADER

    return _INVALID_MARK.sub(repl, output)


def _ambiguous(tok: str, matches: list[str]) -> str:
    return (
        f"% Ambiguous command: \"{tok}\"\n"
        f"  Possible completions: {', '.join(sorted(matches))}"
    )
