"""
simulator_core.cli
~~~~~~~~~~~~~~~~~~
Educational Cisco-style CLI for the NetLab Academy simulator.

Design principles (from PROJECT_SPEC.md §6.5):
- CLI is a command parser + configuration interface, NOT an IOS shell.
- All commands go through an explicit allowlisted grammar.
- Unsupported commands return the standard Cisco error message.
- Device state is the source of truth; CLI output is rendered from state.
- No eval(), no shell execution, no arbitrary Python.

Supported modes:
  USER_EXEC     — prompt ends with >   (e.g. "PC-A>")
  PRIV_EXEC     — prompt ends with #   (e.g. "PC-A#")
  GLOBAL_CONFIG — prompt ends with (config)#
  IFACE_CONFIG  — prompt ends with (config-if)#

Supported commands (host devices):
  User EXEC:
    ping <ip>  [repeat <n>]
    show version
    exit
  Privileged EXEC:
    show ip interface brief
    show interfaces
    show arp
    show version
    configure terminal
    disable
    exit / end
  Global config:
    hostname <name>
    interface <iface>
    exit / end
  Interface config:
    ip address <ip> <mask>
    no ip address
    shutdown
    no shutdown
    description <text>
    exit / end

Supported commands (switch devices):
  User EXEC:
    show version
    exit
  Privileged EXEC:
    show mac address-table
    show interfaces
    show ip interface brief
    show version
    configure terminal
    disable
    exit / end
  Global config:
    hostname <name>
    interface <iface>
    exit / end
  Interface config:
    description <text>
    shutdown
    no shutdown
    exit / end

No host I/O, no sockets, no subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from ipaddress import IPv4Address, IPv4Network, NetmaskValueError
from typing import TYPE_CHECKING, Optional

from simulator_core.exceptions import UnsupportedCommandError

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

class CLIMode(Enum):
    USER_EXEC    = auto()
    PRIV_EXEC    = auto()
    GLOBAL_CONFIG = auto()
    IFACE_CONFIG  = auto()


# ---------------------------------------------------------------------------
# CLI session (one per device)
# ---------------------------------------------------------------------------

@dataclass
class CLISession:
    """
    Represents an active terminal session on a simulated device.

    One CLISession exists per open terminal window.  Multiple sessions
    on the same device are independent (they share device state but have
    separate mode/context tracking).
    """
    device_id: str
    simulation: "Simulation"
    mode: CLIMode = CLIMode.USER_EXEC
    current_iface: Optional[str] = None  # name when in IFACE_CONFIG

    # ── Public API ────────────────────────────────────────────────────────────

    def prompt(self) -> str:
        """Return the current prompt string."""
        device = self.simulation.topology.devices.get(self.device_id)
        hostname = device.hostname if device else self.device_id

        if self.mode == CLIMode.USER_EXEC:
            return f"{hostname}>"
        if self.mode == CLIMode.PRIV_EXEC:
            return f"{hostname}#"
        if self.mode == CLIMode.GLOBAL_CONFIG:
            return f"{hostname}(config)#"
        if self.mode == CLIMode.IFACE_CONFIG:
            return f"{hostname}(config-if)#"
        return f"{hostname}>"

    def execute(self, raw_input: str) -> str:
        """
        Parse and execute a single command line.

        Returns the formatted output string (may be empty for commands
        that produce no output, e.g. hostname change).

        Never raises an exception — unrecognised input returns the
        standard Cisco error: ``% Invalid input detected at '^' marker.``
        """
        line = raw_input.strip()
        if not line:
            return ""

        tokens = line.split()
        cmd = tokens[0].lower()

        # Universal exit / end
        if cmd in ("exit", "end", "quit"):
            return self._handle_exit()

        # Dispatch by mode
        try:
            if self.mode == CLIMode.USER_EXEC:
                return self._user_exec(tokens)
            if self.mode == CLIMode.PRIV_EXEC:
                return self._priv_exec(tokens)
            if self.mode == CLIMode.GLOBAL_CONFIG:
                return self._global_config(tokens)
            if self.mode == CLIMode.IFACE_CONFIG:
                return self._iface_config(tokens)
        except UnsupportedCommandError as exc:
            return str(exc)

        return _invalid(line)

    # ── Mode handlers ─────────────────────────────────────────────────────────

    def _user_exec(self, tokens: list[str]) -> str:
        cmd = tokens[0].lower()

        if cmd == "enable":
            self.mode = CLIMode.PRIV_EXEC
            return ""

        if cmd == "ping":
            return self._do_ping(tokens)

        if cmd == "show":
            return self._show(tokens, allow_privileged=False)

        if cmd == "?":
            return _help_user()

        return _invalid(" ".join(tokens))

    def _priv_exec(self, tokens: list[str]) -> str:
        cmd = tokens[0].lower()

        if cmd == "disable":
            self.mode = CLIMode.USER_EXEC
            return ""

        if cmd == "configure":
            sub = tokens[1].lower() if len(tokens) > 1 else ""
            if sub in ("terminal", "t"):
                self.mode = CLIMode.GLOBAL_CONFIG
                return "Enter configuration commands, one per line.  End with CNTL/Z."
            return _invalid(" ".join(tokens))

        if cmd == "ping":
            return self._do_ping(tokens)

        if cmd == "show":
            return self._show(tokens, allow_privileged=True)

        if cmd == "?":
            return _help_priv()

        return _invalid(" ".join(tokens))

    def _global_config(self, tokens: list[str]) -> str:
        cmd = tokens[0].lower()

        if cmd == "hostname":
            if len(tokens) < 2:
                return "% Incomplete command."
            new_name = tokens[1]
            device = self.simulation.topology.devices.get(self.device_id)
            if device:
                device.hostname = new_name
            return ""

        if cmd == "interface":
            return self._enter_interface(tokens)

        if cmd == "?":
            return _help_global()

        return _invalid(" ".join(tokens))

    def _iface_config(self, tokens: list[str]) -> str:
        cmd = tokens[0].lower()
        device = self.simulation.topology.devices.get(self.device_id)

        if cmd == "ip":
            return self._iface_ip(tokens, device)

        if cmd == "no":
            return self._iface_no(tokens, device)

        if cmd == "shutdown":
            iface = _get_iface(device, self.current_iface)
            if iface:
                from simulator_core.types import InterfaceState
                iface.admin_state = InterfaceState.DOWN
                iface.oper_state = InterfaceState.DOWN
            return ""

        if cmd == "description":
            # Store description as a simple attribute (not in base model yet)
            iface = _get_iface(device, self.current_iface)
            if iface and len(tokens) > 1:
                iface._description = " ".join(tokens[1:])  # type: ignore[attr-defined]
            return ""

        if cmd == "?":
            return _help_iface()

        return _invalid(" ".join(tokens))

    # ── Exit ──────────────────────────────────────────────────────────────────

    def _handle_exit(self) -> str:
        if self.mode == CLIMode.IFACE_CONFIG:
            self.mode = CLIMode.GLOBAL_CONFIG
            self.current_iface = None
        elif self.mode == CLIMode.GLOBAL_CONFIG:
            self.mode = CLIMode.PRIV_EXEC
        elif self.mode == CLIMode.PRIV_EXEC:
            self.mode = CLIMode.USER_EXEC
        # USER_EXEC: exit closes the session — caller decides what to do
        return ""

    # ── Interface entry ───────────────────────────────────────────────────────

    def _enter_interface(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        iface_name = tokens[1]
        device = self.simulation.topology.devices.get(self.device_id)
        if device and iface_name not in device.interfaces:
            return f"% Invalid interface name: {iface_name}"
        self.mode = CLIMode.IFACE_CONFIG
        self.current_iface = iface_name
        return ""

    # ── Interface IP ──────────────────────────────────────────────────────────

    def _iface_ip(self, tokens: list[str], device) -> str:  # type: ignore[type-arg]
        sub = tokens[1].lower() if len(tokens) > 1 else ""
        if sub == "address":
            if len(tokens) < 4:
                return "% Incomplete command."
            ip_str = tokens[2]
            mask_str = tokens[3]
            try:
                ip = IPv4Address(ip_str)
                # Convert dotted mask to prefix length
                mask_int = int(IPv4Address(mask_str))
                prefix = bin(mask_int).count("1")
                if prefix < 0 or prefix > 32:
                    raise ValueError
                cidr = f"{ip}/{prefix}"
            except (ValueError, NetmaskValueError):
                return f"% Invalid IP address: {ip_str} {mask_str}"
            iface = _get_iface(device, self.current_iface)
            if iface:
                try:
                    iface.set_ip(cidr)
                except Exception as exc:
                    return f"% {exc}"
            return ""
        return _invalid(" ".join(tokens))

    def _iface_no(self, tokens: list[str], device) -> str:  # type: ignore[type-arg]
        sub = tokens[1].lower() if len(tokens) > 1 else ""
        iface = _get_iface(device, self.current_iface)
        if sub == "shutdown":
            if iface:
                from simulator_core.types import InterfaceState
                iface.admin_state = InterfaceState.UP
                iface.oper_state = InterfaceState.UP
            return ""
        if sub == "ip":
            if iface:
                iface.ip_config = None
            return ""
        return _invalid(" ".join(tokens))

    # ── Ping ──────────────────────────────────────────────────────────────────

    def _do_ping(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command.\nUsage: ping <ip-address>"

        target = tokens[1]
        repeat = 5
        for i, t in enumerate(tokens):
            if t.lower() == "repeat" and i + 1 < len(tokens):
                try:
                    repeat = max(1, min(100, int(tokens[i + 1])))
                except ValueError:
                    pass

        # Validate target IP
        try:
            IPv4Address(target)
        except ValueError:
            return f"% Bad IP address or host name -- {target!r}"

        from simulator_core.exceptions import ConfigurationError
        try:
            host = self.simulation.get_host(self.device_id)
        except KeyError:
            return "% Ping not supported on this device type."

        try:
            result = host.ping(target, count=repeat)
        except ConfigurationError as exc:
            return f"% {exc}"

        self.simulation.run()

        # Cisco-style output
        lines = [
            f"\nType escape sequence to abort.",
            f"Sending {result.sent}, 100-byte ICMP Echos to {target}, timeout is 2 seconds:",
        ]

        symbols = ""
        for r in result.results:
            symbols += "!" if r.success else "."

        lines.append(symbols)

        if result.sent > 0:
            pct = int(result.received / result.sent * 100)
        else:
            pct = 0

        lines.append(
            f"Success rate is {pct} percent ({result.received}/{result.sent})"
        )

        if result.received > 0:
            rtts = [r.rtt_ticks for r in result.results if r.success and r.rtt_ticks is not None]
            if rtts:
                lines[-1] += f", round-trip min/avg/max = {min(rtts)}/{sum(rtts)//len(rtts)}/{max(rtts)} ticks"

        # Surface the drop reason if all failed
        if result.received == 0 and result.results:
            reason = result.results[0].drop_reason
            if reason:
                lines.append(f"% {reason}")

        return "\n".join(lines)

    # ── Show commands ─────────────────────────────────────────────────────────

    def _show(self, tokens: list[str], allow_privileged: bool) -> str:
        sub = tokens[1].lower() if len(tokens) > 1 else ""

        if sub == "version":
            return _show_version()

        if sub == "ip":
            return self._show_ip(tokens)

        if sub == "interfaces":
            return self._show_interfaces()

        if sub == "arp":
            return self._show_arp()

        if sub in ("mac", "mac-address-table"):
            return self._show_mac()

        if sub == "running-config":
            return self._show_running()

        # Try to show what's available
        available = ["version", "ip interface brief", "interfaces", "arp"]
        device = self.simulation.topology.devices.get(self.device_id)
        if device:
            from simulator_core.types import DeviceModel
            if device.model == DeviceModel.SWITCH:
                available.append("mac address-table")
        return (
            f"% Unrecognized show sub-command: {sub!r}\n"
            f"Available: {', '.join(available)}"
        )

    def _show_ip(self, tokens: list[str]) -> str:
        sub2 = tokens[2].lower() if len(tokens) > 2 else ""
        if sub2 in ("interface", "interfaces"):
            return self._show_ip_interface_brief()
        return _invalid(" ".join(tokens))

    def _show_ip_interface_brief(self) -> str:
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        lines = [
            "Interface                  IP-Address      OK? Method Status                Protocol",
        ]
        for name, iface in device.interfaces.items():
            ip = str(iface.ip_config.address) if iface.ip_config else "unassigned"
            ok = "YES" if iface.ip_config else "NO "
            method = "manual" if iface.ip_config else "unset "
            from simulator_core.types import InterfaceState
            status = "up      " if iface.admin_state == InterfaceState.UP else "administratively down"
            proto  = "up    " if iface.oper_state  == InterfaceState.UP else "down  "
            lines.append(f"{name:<26} {ip:<15} {ok}  {method:<6} {status:<21} {proto}")
        return "\n".join(lines)

    def _show_interfaces(self) -> str:
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        blocks = []
        from simulator_core.types import InterfaceState
        for name, iface in device.interfaces.items():
            status = "up" if iface.admin_state == InterfaceState.UP else "administratively down"
            proto  = "up" if iface.oper_state  == InterfaceState.UP else "down"
            ip_line = ""
            if iface.ip_config:
                ip_line = f"\n  Internet address is {iface.ip_config.address}/{iface.ip_config.prefix_length}"
            desc = getattr(iface, "_description", "")
            desc_line = f"\n  Description: {desc}" if desc else ""
            blocks.append(
                f"{name} is {status}, line protocol is {proto}{desc_line}{ip_line}\n"
                f"  Hardware is Ethernet, address is {iface.mac}\n"
                f"     {iface.rx_frames} packets input, {iface.tx_frames} packets output"
            )
        return "\n".join(blocks)

    def _show_arp(self) -> str:
        try:
            host = self.simulation.get_host(self.device_id)
        except KeyError:
            return "% show arp is not supported on this device type."
        cache = host.arp_cache
        if not cache:
            return "Protocol  Address          Age (min)  Hardware Addr   Type   Interface\n(empty)"
        lines = ["Protocol  Address          Age (min)  Hardware Addr   Type   Interface"]
        for ip, mac in cache.items():
            lines.append(f"Internet  {str(ip):<16} -          {mac}   ARPA   eth0")
        return "\n".join(lines)

    def _show_mac(self) -> str:
        try:
            switch = self.simulation.get_switch(self.device_id)
        except KeyError:
            return "% show mac address-table is only supported on switch devices."
        table = switch.mac_table
        lines = [
            "          Mac Address Table",
            "-------------------------------------------\n",
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

    def _show_running(self) -> str:
        device = self.simulation.topology.devices.get(self.device_id)
        if not device:
            return "% Device not found."
        from simulator_core.types import InterfaceState
        lines = [
            "Building configuration...\n",
            "Current configuration:",
            "!",
            f"hostname {device.hostname}",
            "!",
        ]
        for name, iface in device.interfaces.items():
            lines.append(f"interface {name}")
            desc = getattr(iface, "_description", "")
            if desc:
                lines.append(f" description {desc}")
            if iface.ip_config:
                # Convert prefix to dotted mask
                from ipaddress import IPv4Network
                net = IPv4Network(f"0.0.0.0/{iface.ip_config.prefix_length}", strict=False)
                mask = str(net.netmask)
                lines.append(f" ip address {iface.ip_config.address} {mask}")
            if iface.admin_state == InterfaceState.DOWN:
                lines.append(" shutdown")
            lines.append("!")
        lines.append("end")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_iface(device, name: Optional[str]):
    if device is None or name is None:
        return None
    return device.interfaces.get(name)


def _invalid(cmd: str) -> str:
    """Standard Cisco invalid-input error."""
    # Find first token position for the caret
    stripped = cmd.lstrip()
    return f"% Invalid input detected at '^' marker.\n\n        {stripped}\n        ^"


def _show_version() -> str:
    return (
        "NetLab Academy Educational Simulator\n"
        "Version 0.1.0 (simulator-core)\n"
        "Copyright (c) NetLab Academy — educational use only.\n"
        "This is not Cisco IOS. Supported commands are documented.\n"
        "\nUptime: N/A (discrete-event simulation)\n"
        "Processor board ID: EDUCATIONAL\n"
    )


def _help_user() -> str:
    return (
        "User EXEC commands:\n"
        "  enable        Enter privileged EXEC mode\n"
        "  ping          Send ICMP echo messages\n"
        "  show          Show system information\n"
        "  exit          Exit current mode\n"
    )


def _help_priv() -> str:
    return (
        "Privileged EXEC commands:\n"
        "  configure terminal   Enter global configuration mode\n"
        "  disable              Exit privileged EXEC mode\n"
        "  ping                 Send ICMP echo messages\n"
        "  show                 Show system information\n"
        "  exit                 Exit current mode\n"
    )


def _help_global() -> str:
    return (
        "Global configuration commands:\n"
        "  hostname <name>      Set device hostname\n"
        "  interface <name>     Enter interface configuration\n"
        "  exit                 Exit to privileged EXEC\n"
    )


def _help_iface() -> str:
    return (
        "Interface configuration commands:\n"
        "  ip address <ip> <mask>   Set IP address\n"
        "  no ip address            Remove IP address\n"
        "  shutdown                 Disable interface\n"
        "  no shutdown              Enable interface\n"
        "  description <text>       Set description\n"
        "  exit                     Exit to global config\n"
    )
