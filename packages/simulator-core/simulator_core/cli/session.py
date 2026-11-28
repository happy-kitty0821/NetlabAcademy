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
from typing import Optional, TYPE_CHECKING

from simulator_core.cli.cdp import CdpCommands
from simulator_core.cli.engine import (
    _ambiguous,
    CLIMode,
    Cmd,
    _CONFIG_MODES,
    _format_help,
    _invalid,
    _invalid_at,
    _INVALID_HEADER,
    _match,
    _render_invalid,
    _step,
)
from simulator_core.cli.etherchannel import EtherChannelCommands
from simulator_core.cli.interfaces import InterfaceCommands
from simulator_core.cli.routing import RoutingCommands
from simulator_core.cli.stp import StpCommands
from simulator_core.cli.switching import SwitchingCommands
from simulator_core.cli.system import SystemCommands
from simulator_core.cli.trees import CommandTrees
from simulator_core.cli.vlan import VlanCommands


if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


@dataclass
class CLISession(
    CommandTrees,
    SystemCommands,
    InterfaceCommands,
    VlanCommands,
    StpCommands,
    SwitchingCommands,
    EtherChannelCommands,
    CdpCommands,
    RoutingCommands,
):
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
            keywords = [c.keyword for c in node_list if c.arg is None]
            matches = _match(tok, keywords)
            if not is_last and not matches:
                # A value typed for an argument placeholder ("1-100").
                _, arg_node = _step(tok, node_list)
                if arg_node is not None:
                    completed_tokens.append(tok)
                    node_list = arg_node.children
                    continue

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
                    child = next(c for c in node_list
                                 if c.keyword == matches[0] and c.arg is None)
                    node_list = child.children
                elif len(matches) == 0:
                    # No match — return unchanged
                    return partial.rstrip()
                else:
                    completed_tokens.append(tok)
                    return " ".join(completed_tokens)

        return partial.rstrip()

    def _tree(self) -> list[Cmd]:
        """Return the command list for the current mode."""
        if self.mode in (CLIMode.USER_EXEC, CLIMode.PRIV_EXEC):
            tree = self._user_tree() if self.mode == CLIMode.USER_EXEC else self._priv_tree()
            if self._is_host():
                tree = tree + [Cmd("ipconfig", "Show or set this PC's IP configuration",
                                   args_hint="[<ip> <mask> [<gateway>]]",
                                   handler=lambda s, t: s._cmd_ipconfig(t))]
            return tree
        if self.mode == CLIMode.GLOBAL_CONFIG:
            return self._global_tree()
        if self.mode == CLIMode.IFACE_CONFIG:
            return self._iface_tree()
        if self.mode == CLIMode.VLAN_CONFIG:
            return self._vlan_tree()
        if self.mode == CLIMode.LINE_CONFIG:
            return self._line_tree()
        return []

    def _dispatch(self, tokens: list[str], tree: list[Cmd]) -> str:
        """
        Walk the command tree matching tokens with prefix expansion.
        Returns the handler output or an error string.
        """
        node_list = tree
        matched_path: list[str] = []
        parent_fallback: Optional[Cmd] = None

        for depth, tok in enumerate(tokens):
            matches, cmd_node = _step(tok, node_list)

            if len(matches) == 0:
                if depth > 0 and parent_fallback is not None:
                    return parent_fallback.handler(self, tokens)
                if depth == 0:
                    return _invalid(tok)
                # Unknown sub-command after a valid prefix
                bad = " ".join(tokens[:depth] + [tok])
                return _invalid_at(bad, tok)

            if cmd_node is None:
                return _ambiguous(tok, matches)

            matched_path.append(cmd_node.keyword)

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
                _, node = _step(tok, node_list)
                if node is None:
                    return "% Unrecognized command"
                node_list = node.children
            partial = tokens[-1].lower()
            words = [c.keyword for c in node_list
                     if c.arg is None and c.keyword.lower().startswith(partial)]
            return "  ".join(words) if words else "% Unrecognized command"

        # Walk tree to find current context
        for depth, tok in enumerate(tokens):
            matches, cmd_node = _step(tok, node_list)

            if len(matches) == 0:
                if any(c.arg is not None for c in node_list):
                    return _invalid_at(" ".join(tokens[:depth + 1]), tok)
                return f"% No help available for {tok!r}"
            if cmd_node is None:
                return _format_help([c for c in node_list if c.keyword in matches])

            if depth == len(tokens) - 1:
                # Last token — show children of this node, and <cr> when the
                # command is already complete here.
                if cmd_node.children:
                    help_text = _format_help(cmd_node.children)
                    if cmd_node.handler is not None:
                        help_text += "\n  <cr>"
                    return help_text
                if cmd_node.arg is not None:
                    return "  <cr>"
                if cmd_node.args_hint:
                    return f"  {cmd_node.args_hint:<30} {cmd_node.help_str}"
                return f"  <cr>{'':26} {cmd_node.help_str}"

            node_list = cmd_node.children
            if not node_list:
                return f"  <cr>"

        # Should not reach here
        return _format_help(node_list)

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

    def _cmd_conf_prompt(self, tokens: list[str]) -> str:
        self.pending_input = "conf_source"
        return ""

    def _cmd_disable(self, tokens: list[str]) -> str:
        self.mode = CLIMode.USER_EXEC
        return ""

    def _cmd_conf_terminal(self, tokens: list[str]) -> str:
        self.mode = CLIMode.GLOBAL_CONFIG
        return "Enter configuration commands, one per line.  End with CNTL/Z."

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

    def _is_host(self) -> bool:
        from simulator_core.types import DeviceModel
        device = self.simulation.topology.devices.get(self.device_id)
        return device is not None and device.model == DeviceModel.HOST

    def _get_switch(self):
        """Return the Switch object for this session, or None."""
        try:
            return self.simulation.get_switch(self.device_id)
        except KeyError:
            return None

    def _get_router(self):
        """Return the Router object for this session, or None."""
        try:
            return self.simulation.get_router(self.device_id)
        except KeyError:
            return None

    def _get_config(self):
        """Return the DeviceConfig for this session's device."""
        device = self.simulation.topology.devices.get(self.device_id)
        return device.config if device else None
