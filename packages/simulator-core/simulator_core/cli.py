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
            CLIMode.LINE_CONFIG:   "(config-line)#",
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
            return self._cmd_end(["end"])

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
                ],
                # 'configure' alone also works as 'configure terminal'
                handler=lambda s, t: s._cmd_conf_terminal(t)),
            Cmd("enable",    "Enter privileged EXEC mode (already enabled)",
                handler=lambda s, t: ""),
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
                        handler=lambda s, t: "Building configuration...\n[OK]"),
                    Cmd("terminal", "Write to terminal",
                        handler=lambda s, t: s._cmd_show_running(t)),
                    Cmd("erase",    "Erase the startup configuration",
                        handler=lambda s, t: "Erasing the nvram filesystem will remove all configuration files! Continue? [confirm]y\n[OK]\nErase of nvram: complete"),
                ],
                # 'write' alone defaults to 'write memory'
                handler=lambda s, t: "Building configuration...\n[OK]"),
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
                ]),
            Cmd("ip",         "IP configuration",
                children=[
                    Cmd("routing", "Enable IP routing",
                        handler=lambda s, t: ""),
                    Cmd("route",   "Establish a static route",
                        args_hint="<network> <mask> <next-hop>",
                        handler=lambda s, t: s._cmd_ip_route(t)),
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
                    Cmd("nonegotiate", "Disable DTP negotiation",
                        handler=lambda s, t: ""),
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
                        handler=lambda s, t: s._show_ip_iface_dispatch(t)),
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
                handler=lambda s, t: "% startup-config: not supported in this simulator."),
            Cmd("vlan",        "VTP VLAN status",
                children=[
                    Cmd("brief", "VTP management domain status",
                        handler=lambda s, t: s._cmd_show_vlan_brief(t)),
                ],
                handler=lambda s, t: s._cmd_show_vlan_brief(t)),
            Cmd("cdp",         "CDP information (not simulated)",
                handler=lambda s, t: "% CDP: not supported in this simulator."),
            Cmd("clock",       "Display the system clock",
                handler=lambda s, t: f"% Logical clock: tick {self.simulation.clock}"),
            Cmd("history",     "Display the session command history",
                handler=lambda s, t: "% Command history: not yet implemented."),
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
                    Cmd("status",  "Brief interface status",
                        handler=lambda s, t: s._cmd_show_interfaces_status(t)),
                    Cmd("brief",   "Brief IP interface summary",
                        handler=lambda s, t: s._cmd_show_ip_int_brief(t)),
                ] + [
                    Cmd(name, f"Interface {name}",
                        handler=lambda s, t, n=name: s._cmd_show_interface(t, n))
                    for name in self._iface_names()
                ],
                handler=lambda s, t: s._show_interfaces_dispatch(t)),
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
        elif self.mode == CLIMode.LINE_CONFIG:
            self.mode = CLIMode.GLOBAL_CONFIG
            self.current_line = None
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
        sub = tokens[1].lower()

        # Dispatch sub-types handled inline so the tree stays simple
        if sub == "range":
            return self._cmd_enter_iface_range(tokens)
        if sub == "vlan":
            return self._cmd_enter_svi(tokens)
        if sub in ("loopback", "lo"):
            return self._cmd_enter_loopback(tokens)

        iface_name = tokens[1]
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        iface_names = list(device.interfaces.keys())

        # Match with Cisco abbreviation support
        matches = _match_iface(iface_name, iface_names)
        if not matches:
            return f"% Invalid interface name: {iface_name!r}"
        if len(matches) > 1:
            exact = [n for n in matches if n.lower() == iface_name.lower()]
            if exact:
                matches = exact
            else:
                return (
                    f"% Ambiguous interface: {iface_name!r}\n"
                    f"  Matches: {', '.join(matches)}"
                )
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = matches[0]
        return ""

    def _cmd_enter_iface_range(self, tokens: list[str]) -> str:
        # tokens: ['interface', 'range', '<iface1>', '-', '<iface2>']
        # For now, enter the first interface in the range
        if len(tokens) < 4:
            return "% Incomplete command.\nUsage: interface range <iface1> - <iface2>"
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        iface_names = list(device.interfaces.keys())
        first_name = tokens[2]
        matches = _match_iface(first_name, iface_names)
        if not matches:
            return f"% Invalid interface name: {first_name!r}"
        # Enter the first interface; the range concept applies config to all
        # but for the PoC we enter the first one and note the range
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = matches[0]
        # Store the range for potential future use
        if len(tokens) > 4 and tokens[3] == "-":
            device._iface_range = tokens[2:]  # type: ignore[attr-defined]
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
        iface_name = f"Vlan{vlan_id}"
        if iface_name not in device.interfaces:
            # Create the SVI interface
            from simulator_core.addresses import MACAddress
            import random
            iface = Interface(
                name=iface_name,
                mac=MACAddress.generate(random.Random(hash(iface_name) % 1000)),
            )
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
            from simulator_core.addresses import MACAddress
            import random
            iface = Interface(
                name=iface_name,
                mac=MACAddress.generate(random.Random(hash(iface_name) % 1000)),
            )
            device.add_interface(iface)
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = iface_name
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

    # ── Static routing commands ───────────────────────────────────────────────

    def _get_router(self):
        """Return the Router object for this session, or None."""
        try:
            return self.simulation.get_router(self.device_id)
        except KeyError:
            return None

    def _parse_network_and_mask(self, net_str: str, mask_str: str):
        """Parse a network + dotted-mask pair, return IPv4Network or None."""
        from ipaddress import IPv4Address, IPv4Network
        try:
            if "." in mask_str:
                # Dotted mask like 255.255.255.0
                prefix = bin(int(IPv4Address(mask_str))).count("1")
            else:
                prefix = int(mask_str)
            return IPv4Network(f"{net_str}/{prefix}", strict=False)
        except Exception:
            return None

    def _cmd_ip_route(self, tokens: list[str]) -> str:
        # tokens: ['ip', 'route', '<network>', '<mask>', '<next-hop>']
        if len(tokens) < 5:
            return "% Incomplete command.\nUsage: ip route <network> <mask> <next-hop>"
        net_str, mask_str, nh_str = tokens[2], tokens[3], tokens[4]
        network = self._parse_network_and_mask(net_str, mask_str)
        if network is None:
            return f"% Invalid network or mask: {net_str} {mask_str}"
        from ipaddress import IPv4Address
        try:
            next_hop = IPv4Address(nh_str)
        except ValueError:
            return f"% Invalid next-hop address: {nh_str!r}"
        router = self._get_router()
        if router is None:
            return "% ip route is only available on router devices."
        # Find the outgoing interface for this next-hop
        # Look for the interface whose subnet contains the next-hop
        iface_name = None
        for name, iface in self.simulation.topology.devices[self.device_id].interfaces.items():
            if iface.ip_config and next_hop in iface.ip_config.network:
                iface_name = name
                break
        if iface_name is None:
            # Still add the route — the interface will be found at forward time
            # Try to find any UP interface as a default
            for name, iface in self.simulation.topology.devices[self.device_id].interfaces.items():
                from simulator_core.types import InterfaceState
                if iface.admin_state == InterfaceState.UP:
                    iface_name = name
                    break
        if iface_name is None:
            return "% No suitable interface found for this static route."
        router.routing_table.add_static_route(network, next_hop, iface_name)
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
        iface = self._get_current_iface()
        if iface:
            iface.switchport_mode = "access"
        return ""

    def _cmd_switchport_mode_trunk(self, tokens: list[str]) -> str:
        """switchport mode trunk"""
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
        iface = self._get_current_iface()
        if iface:
            iface.switchport_mode = f"dynamic_{mode}"
        return ""

    def _cmd_switchport_trunk_native_vlan(self, tokens: list[str]) -> str:
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
        iface = self._get_current_iface()
        if iface:
            iface.trunk_encapsulation = encap
        return ""

    def _cmd_switchport_port_security(self, tokens: list[str]) -> str:
        """Basic port security (store config; enforcement not yet simulated)."""
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

    def _cmd_no_switchport(self, tokens: list[str]) -> str:
        iface = self._get_current_iface()
        if iface:
            iface.vlan = 1
            iface.switchport_mode = "access"
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
                switch.stp.set_root_primary(vlan_id)
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
        return switch.stp.show_spanning_tree(vlan_id)

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
        return switch.stp.show_spanning_tree_brief()

    # ── Show interfaces trunk / status ────────────────────────────────────────

    def _cmd_show_interfaces_trunk(self, tokens: list[str]) -> str:
        """show interfaces trunk — Cisco-style trunk info table."""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        switch = self._get_switch()

        trunk_ifaces = [
            (name, iface)
            for name, iface in device.interfaces.items()
            if iface.switchport_mode == "trunk"
        ]

        if not trunk_ifaces:
            return "% No trunk interfaces configured."

        lines = [
            "Port        Mode         Encapsulation  Status        Native vlan",
        ]
        for name, iface in trunk_ifaces:
            status = "trunking" if iface.admin_state == InterfaceState.UP else "not-trunking"
            mode_abbr = "on"
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
        """show interfaces status — brief port status table."""
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        from simulator_core.types import InterfaceState

        lines = [
            "Port      Name               Status       Vlan       Duplex  Speed Type",
        ]
        for name, iface in device.interfaces.items():
            status = "connected" if iface.admin_state == InterfaceState.UP else "notconnect"
            mode = iface.switchport_mode
            if mode == "trunk":
                vlan_field = "trunk"
            elif mode == "access":
                vlan_field = str(iface.vlan)
            else:
                vlan_field = "routed"
            desc = getattr(iface, "_description", "")[:18]
            lines.append(
                f"{name:<9} {desc:<18} {status:<12} {vlan_field:<10} a-full  a-100 10/100BaseTX"
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
        line_type_str = tokens[1].lower()
        from simulator_core.device_config import LineType
        if line_type_str == "console":
            self.mode = CLIMode.LINE_CONFIG
            self.current_line = "console 0"
            return ""
        elif line_type_str == "vty":
            first = int(tokens[2]) if tokens[2].isdigit() else 0
            last = int(tokens[3]) if len(tokens) > 3 and tokens[3].isdigit() else first
            self.mode = CLIMode.LINE_CONFIG
            self.current_line = f"vty {first} {last}" if last > first else f"vty {first}"
            return ""
        elif line_type_str == "aux":
            self.mode = CLIMode.LINE_CONFIG
            self.current_line = "aux 0"
            return ""
        return f"% Invalid line type: {line_type_str!r}"

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
        # Cisco uses delimiters; for simplicity we take the rest as the text
        text = " ".join(tokens[2:]).strip("^C").strip()
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

    def _show_ip_iface_dispatch(self, tokens: list[str]) -> str:
        """Dispatch 'show ip interface <name>' with fuzzy match."""
        sub = tokens[2].lower() if len(tokens) > 2 else ""
        if sub in ("brief", "bri", "br"):
            return self._cmd_show_ip_int_brief(tokens)
        if len(tokens) > 2:
            # Try fuzzy match on the interface name token
            device = self.simulation.topology.devices.get(self.device_id)
            if device:
                matches = _match_iface(tokens[2], list(device.interfaces.keys()))
                if matches:
                    return self._cmd_show_ip_iface(tokens, matches[0])
        return self._cmd_show_ip_int_brief(tokens)

    def _show_interfaces_dispatch(self, tokens: list[str]) -> str:
        """Dispatch 'show interfaces [<name>]' with fuzzy match."""
        if len(tokens) < 3:
            return self._cmd_show_interfaces_all(tokens)
        sub = tokens[2].lower()
        if sub in ("brief", "bri", "br"):
            return self._cmd_show_ip_int_brief(tokens)
        # Fuzzy match on interface name
        device = self.simulation.topology.devices.get(self.device_id)
        if device:
            matches = _match_iface(tokens[2], list(device.interfaces.keys()))
            if matches:
                return self._cmd_show_interface(tokens, matches[0])
        return self._cmd_show_interfaces_all(tokens)

    def _show_running_iface_dispatch(self, tokens: list[str]) -> str:
        """Dispatch 'show running-config interface <name>' with fuzzy match."""
        # tokens: ['show', 'running-config', 'interface', '<name>']
        if len(tokens) < 4:
            return "% Incomplete command."
        iface_name = tokens[3]
        device = self.simulation.topology.devices.get(self.device_id)
        if device:
            matches = _match_iface(iface_name, list(device.interfaces.keys()))
            if matches:
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
        try:
            router = self.simulation.get_router(self.device_id)
        except KeyError:
            return "% show ip route is only available on router devices."

        rt = router.routing_table
        if not rt.routes:
            return "% No routes in routing table."

        source_codes = {
            "CONNECTED": "C",
            "STATIC":    "S",
        }

        lines = [
            "Codes: C - connected, S - static\n",
            "Gateway of last resort is not set\n",
        ]
        for entry in rt.routes:
            code = source_codes.get(entry.source.name, "?")
            if entry.next_hop:
                via = f" via {entry.next_hop}"
            else:
                via = f", directly connected"
            lines.append(f"{code}    {str(entry.network):<20} [{entry.metric}/0]{via}, {entry.outgoing_interface}")
        return "\n".join(lines)

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
        ]
        # Device-level config lines (users, lines, logging, etc.)
        lines += device.config.show_running_config_lines()
        lines += [
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
            if hasattr(iface, "switchport_mode") and iface.switchport_mode == "access":
                lines.append(f" switchport mode access")
                if iface.vlan != 1:
                    lines.append(f" switchport access vlan {iface.vlan}")
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
            f"interface {matches[0]}",
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

# Cisco interface type abbreviations
_IFACE_PREFIX_MAP = {
    "gi": "Gi", "gig": "Gi", "giga": "Gi", "gigabitethernet": "Gi",
    "fa": "Fa", "fast": "Fa", "fastethernet": "Fa",
    "eth": "eth", "e": "eth",
    "vl": "Vlan", "vlan": "Vlan",
    "lo": "Loopback", "loop": "Loopback", "loopback": "Loopback",
}

def _match_iface(input_name: str, iface_names: list[str]) -> list[str]:
    """
    Match an interface name with Cisco-style abbreviation support.
    
    Tries in order:
    1. Exact match (case-insensitive)
    2. Case-insensitive prefix match
    3. Cisco type abbreviation (gig0/0 -> Gi0/0, fa0/1 -> Fa0/1)
    """
    lower_input = input_name.lower()
    
    # 1. Exact match
    exact = [n for n in iface_names if n.lower() == lower_input]
    if exact:
        return exact
    
    # 2. Case-insensitive prefix match
    prefix_matches = [n for n in iface_names if n.lower().startswith(lower_input)]
    if prefix_matches:
        return prefix_matches
    
    # 3. Cisco abbreviation: try replacing known type prefixes
    for abbrev, full_prefix in _IFACE_PREFIX_MAP.items():
        if lower_input.startswith(abbrev):
            # Replace the abbreviation with the full prefix
            rest = input_name[len(abbrev):]
            normalized = full_prefix + rest
            norm_matches = [n for n in iface_names if n.lower() == normalized.lower()]
            if norm_matches:
                return norm_matches
            # Also try prefix match with the normalized name
            norm_prefix = [n for n in iface_names if n.lower().startswith(normalized.lower())]
            if norm_prefix:
                return norm_prefix
    
    # 4. Try matching just the numeric portion (e.g. "0/0" matches "Gi0/0")
    import re
    num_match = re.search(r'[/\d]+$', lower_input)
    if num_match:
        num_part = num_match.group()
        num_matches = [n for n in iface_names if n.lower().endswith(num_part)]
        if num_matches:
            return num_matches
    
    return []


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
