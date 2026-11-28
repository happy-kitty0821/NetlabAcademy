"""
System commands: hostname, users and passwords, lines, logging,
banners, saving the configuration, ``show version / running-config``.
"""

from __future__ import annotations

from simulator_core.cli.engine import CLIMode, _invalid_at
from simulator_core.cli.helpers import _join_iface_tokens, _long_name, _match_iface
from simulator_core.cli.running_config import (
    _iface_config_lines,
    _stp_global_lines,
    _switch_global_lines,
)


class SystemCommands:
    """System commands: hostname, users and passwords, lines, logging, (mixed into ``CLISession``)."""

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

    def _cmd_terminal(self, tokens: list[str]) -> str:
        # terminal length|width <0-512> — accepted; output is never paged here
        if len(tokens) < 3:
            return "% Incomplete command."
        if not tokens[2].isdigit() or not 0 <= int(tokens[2]) <= 512:
            return _invalid_at(" ".join(tokens[:3]), tokens[2])
        return ""

    def _cmd_hostname(self, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "% Incomplete command."
        device = self.simulation.topology.devices.get(self.device_id)
        if device:
            device.hostname = tokens[1]
        return ""

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

    def _cmd_service_password_encryption(self, tokens: list[str]) -> str:
        config = self._get_config()
        if config:
            config.service_password_encryption = True
        return ""

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

    def _cmd_show_version(self, tokens: list[str]) -> str:
        return (
            "\nNetLab Academy Educational Simulator\n"
            "Version 0.1.0 (simulator-core)\n"
            "Copyright (c) NetLab Academy -- educational use only.\n"
            "This is not Cisco IOS. Supported commands are documented.\n\n"
            f"Uptime: {self.simulation.clock} logical ticks\n"
            "Processor board ID: EDUCATIONAL\n"
        )

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
            lines += _switch_global_lines(switch)
            lines.append("!")
        # IOS lists port-channel interfaces before the physical ports.
        ordered = sorted(device.interfaces.items(), key=lambda kv: not kv[1].is_port_channel)
        for name, iface in ordered:
            # Skip SVIs on devices that don't support them (e.g. L2-only switches).
            # They should not exist — but if one was created before the capability
            # check was enforced, exclude it from the running-config.
            if iface.is_svi and not device.supports_svi:
                continue
            lines.append("!")
            lines += _iface_config_lines(device, name, iface, switch.stp if switch else None,
                                         switch.port_security_config(name) if switch else None)
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
        lines += _iface_config_lines(device, matches[0], iface, switch.stp if switch else None,
                                     switch.port_security_config(matches[0]) if switch else None)
        lines += ["end"]
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
