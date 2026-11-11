"""
simulator_core.device_config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Shared device configuration state — applies equally to switches and routers.

This module defines DeviceConfig, a single object that lives on every
simulated device (switch, router, host) and holds:

  - enable secret / enable password
  - local user accounts
  - console / VTY / AUX line configuration
  - syslog / logging configuration
  - banner MOTD

No host I/O, no sockets, no subprocess.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# Syslog severity levels (RFC 5424)
# ---------------------------------------------------------------------------

class LogSeverity(Enum):
    EMERGENCIES   = 0   # System unusable
    ALERTS        = 1   # Immediate action required
    CRITICAL      = 2   # Critical conditions
    ERRORS        = 3   # Error conditions
    WARNINGS      = 4   # Warning conditions
    NOTIFICATIONS = 5   # Normal but significant
    INFORMATIONAL = 6   # Informational
    DEBUGGING     = 7   # Debug messages

    @classmethod
    def from_name(cls, name: str) -> "LogSeverity":
        """Case-insensitive lookup by name or alias."""
        aliases = {
            "emergencies": cls.EMERGENCIES,
            "alerts":      cls.ALERTS,
            "critical":    cls.CRITICAL,
            "errors":      cls.ERRORS,
            "error":       cls.ERRORS,
            "warnings":    cls.WARNINGS,
            "warning":     cls.WARNINGS,
            "notifications": cls.NOTIFICATIONS,
            "informational": cls.INFORMATIONAL,
            "info":          cls.INFORMATIONAL,
            "debugging":   cls.DEBUGGING,
            "debug":       cls.DEBUGGING,
        }
        result = aliases.get(name.lower())
        if result is None:
            raise ValueError(f"Unknown log severity: {name!r}")
        return result


# ---------------------------------------------------------------------------
# Log entry
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    tick: int
    severity: LogSeverity
    facility: str   # e.g. "SYS", "LINE", "STP"
    message: str

    def __str__(self) -> str:
        return f"*tick {self.tick}: %{self.facility}-{self.severity.value}-{self.severity.name}: {self.message}"


# ---------------------------------------------------------------------------
# User account
# ---------------------------------------------------------------------------

@dataclass
class UserAccount:
    """
    Local user account.

    Password is stored as a salted SHA-256 hash (never in plaintext).
    Privilege level 0–15; level 15 = full admin (like ``privilege 15``).
    """
    username: str
    password_hash: str   # hex SHA-256
    privilege: int = 1   # 1 = user, 15 = privileged

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def check_password(self, password: str) -> bool:
        return self.password_hash == self.hash_password(password)

    @classmethod
    def create(cls, username: str, password: str, privilege: int = 1) -> "UserAccount":
        return cls(
            username=username,
            password_hash=cls.hash_password(password),
            privilege=privilege,
        )


# ---------------------------------------------------------------------------
# Line configuration (console, VTY 0–4, AUX)
# ---------------------------------------------------------------------------

class LineType(Enum):
    CONSOLE = auto()
    VTY     = auto()
    AUX     = auto()


@dataclass
class LineConfig:
    """
    Configuration for one terminal line (console 0, vty 0 4, aux 0).

    exec_timeout: idle timeout in seconds. 0 = disabled (never timeout).
    password:     line-level password (plain-text, stored hashed).
    login:        if True, require password before entering user EXEC.
    login_local:  if True, require local username/password.
    transport_input: list of allowed protocols (e.g. ["ssh", "telnet"]).
    logging_synchronous: if True, suppress log messages interrupting input.
    motd:         whether to show banner motd on this line.
    privilege:    privilege level for this line session.
    """
    line_type: LineType
    line_num: int
    exec_timeout: int = 600        # 10 minutes default
    password_hash: Optional[str] = None
    login: bool = False
    login_local: bool = False
    transport_input: list[str] = field(default_factory=lambda: ["all"])
    logging_synchronous: bool = False
    motd: bool = True
    privilege: int = 1

    def set_password(self, password: str) -> None:
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()

    def check_password(self, password: str) -> bool:
        if self.password_hash is None:
            return True  # no password set
        return self.password_hash == hashlib.sha256(password.encode()).hexdigest()

    @property
    def label(self) -> str:
        if self.line_type == LineType.CONSOLE:
            return f"console {self.line_num}"
        if self.line_type == LineType.VTY:
            return f"vty {self.line_num}"
        return f"aux {self.line_num}"


# ---------------------------------------------------------------------------
# DeviceConfig — the shared config object
# ---------------------------------------------------------------------------

@dataclass
class DeviceConfig:
    """
    All device-level configuration that is shared between switches and routers.

    One DeviceConfig lives on every simulated device.  The CLI reads and
    writes this object directly — no separate "running-config" string.
    """

    # ── Authentication ────────────────────────────────────────────────────────

    # enable secret (type 5 — MD5 hash simulated as SHA-256 for educational use)
    enable_secret_hash: Optional[str] = None
    # enable password (type 0 — stored as hash here for safety)
    enable_password_hash: Optional[str] = None
    # Whether the device requires enable secret/password to enter priv EXEC
    enable_auth_required: bool = False

    # Local user database: username → UserAccount
    users: dict[str, UserAccount] = field(default_factory=dict)

    # ── Lines ─────────────────────────────────────────────────────────────────

    console_line: LineConfig = field(
        default_factory=lambda: LineConfig(LineType.CONSOLE, 0)
    )
    vty_lines: list[LineConfig] = field(
        default_factory=lambda: [
            LineConfig(LineType.VTY, i) for i in range(5)  # vty 0 4
        ]
    )
    aux_line: LineConfig = field(
        default_factory=lambda: LineConfig(LineType.AUX, 0)
    )

    # ── Logging / syslog ──────────────────────────────────────────────────────

    logging_enabled: bool = True
    logging_console_level: LogSeverity = LogSeverity.WARNINGS
    logging_buffered_level: LogSeverity = LogSeverity.DEBUGGING
    logging_buffered_size: int = 4096
    logging_hosts: list[str] = field(default_factory=list)   # syslog server IPs
    logging_facility: str = "local7"
    log_buffer: list[LogEntry] = field(default_factory=list)

    # ── Banner ────────────────────────────────────────────────────────────────

    banner_motd: str = ""
    banner_login: str = ""
    banner_exec: str = ""

    # ── Miscellaneous ─────────────────────────────────────────────────────────

    service_password_encryption: bool = False
    service_timestamps_log: bool = True
    service_timestamps_debug: bool = True
    no_ip_domain_lookup: bool = False
    ip_domain_name: str = ""
    ip_default_gateway: str = ""    # L2 switch management default gateway
    hostname_override: str = ""    # set by 'hostname' command

    # ── Methods ───────────────────────────────────────────────────────────────

    def set_enable_secret(self, secret: str) -> None:
        """Set enable secret (type 5 equivalent)."""
        self.enable_secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        self.enable_auth_required = True

    def set_enable_password(self, password: str) -> None:
        """Set enable password (type 7 equivalent — less secure)."""
        self.enable_password_hash = hashlib.sha256(password.encode()).hexdigest()
        if self.enable_secret_hash is None:
            self.enable_auth_required = True

    def check_enable(self, secret: str) -> bool:
        """Check enable secret first, then enable password."""
        if self.enable_secret_hash:
            return self.enable_secret_hash == hashlib.sha256(secret.encode()).hexdigest()
        if self.enable_password_hash:
            return self.enable_password_hash == hashlib.sha256(secret.encode()).hexdigest()
        return True  # no auth configured

    def add_user(self, username: str, password: str, privilege: int = 1) -> None:
        self.users[username] = UserAccount.create(username, password, privilege)

    def remove_user(self, username: str) -> bool:
        if username in self.users:
            del self.users[username]
            return True
        return False

    def check_user(self, username: str, password: str) -> bool:
        user = self.users.get(username)
        return user is not None and user.check_password(password)

    def add_log(self, tick: int, severity: LogSeverity,
                facility: str, message: str) -> None:
        """Add a log entry to the buffer if severity meets the threshold."""
        if severity.value <= self.logging_buffered_level.value:
            entry = LogEntry(tick=tick, severity=severity,
                             facility=facility, message=message)
            self.log_buffer.append(entry)
            # Cap buffer size
            if len(self.log_buffer) > self.logging_buffered_size // 100:
                self.log_buffer.pop(0)

    def get_vty_line(self, num: int) -> Optional[LineConfig]:
        for vty in self.vty_lines:
            if vty.line_num == num:
                return vty
        return None

    def get_vty_range(self, start: int, end: int) -> list[LineConfig]:
        return [v for v in self.vty_lines if start <= v.line_num <= end]

    def show_running_config_lines(self) -> list[str]:
        """Render device-level config lines for show running-config."""
        lines: list[str] = []

        # service commands
        if self.service_password_encryption:
            lines.append("service password-encryption")
        if self.service_timestamps_log:
            lines.append("service timestamps log datetime msec")
        if self.service_timestamps_debug:
            lines.append("service timestamps debug datetime msec")

        lines.append("!")

        # enable secret / password
        if self.enable_secret_hash:
            lines.append(f"enable secret 5 $1$SIMULATED${self.enable_secret_hash[:22]}")
        elif self.enable_password_hash:
            lines.append(f"enable password 7 {self.enable_password_hash[:14]}")

        # users
        for username, user in self.users.items():
            pw_display = f"5 $1$SIM${user.password_hash[:22]}"
            lines.append(f"username {username} privilege {user.privilege} secret {pw_display}")

        # ip settings
        if self.no_ip_domain_lookup:
            lines.append("no ip domain-lookup")
        if self.ip_domain_name:
            lines.append(f"ip domain-name {self.ip_domain_name}")
        if self.ip_default_gateway:
            lines.append(f"ip default-gateway {self.ip_default_gateway}")

        # logging
        if not self.logging_enabled:
            lines.append("no logging console")
        lines.append(f"logging buffered {self.logging_buffered_size} "
                     f"{self.logging_console_level.name.lower()}")
        for host in self.logging_hosts:
            lines.append(f"logging host {host}")

        # banner
        if self.banner_motd:
            lines.append(f"banner motd ^C\n{self.banner_motd}\n^C")

        lines.append("!")

        # console line
        lines += self._render_line(self.console_line)
        # vty lines (grouped by identical config)
        lines += self._render_vty_lines()
        # aux line
        lines += self._render_line(self.aux_line)

        return lines

    def _render_line(self, line: LineConfig) -> list[str]:
        out = [f"line {line.label}"]
        if line.exec_timeout != 600:
            m, s = divmod(line.exec_timeout, 60)
            out.append(f" exec-timeout {m} {s}")
        if line.login_local:
            out.append(" login local")
        elif line.login and line.password_hash:
            out.append(f" password 7 {line.password_hash[:14]}")
            out.append(" login")
        if line.logging_synchronous:
            out.append(" logging synchronous")
        if line.transport_input != ["all"]:
            out.append(f" transport input {' '.join(line.transport_input)}")
        out.append("!")
        return out

    def _render_vty_lines(self) -> list[str]:
        """Group consecutive VTY lines with identical config."""
        if not self.vty_lines:
            return []
        # Find the first line and check if all 0-4 are the same
        first = self.vty_lines[0]
        same = all(
            v.exec_timeout == first.exec_timeout
            and v.login == first.login
            and v.login_local == first.login_local
            and v.transport_input == first.transport_input
            for v in self.vty_lines
        )
        if same:
            # Render as a range: "line vty 0 4"
            start = self.vty_lines[0].line_num
            end = self.vty_lines[-1].line_num
            line = LineConfig(LineType.VTY, start)
            line.exec_timeout = first.exec_timeout
            line.login = first.login
            line.login_local = first.login_local
            line.transport_input = first.transport_input
            line.logging_synchronous = first.logging_synchronous
            line.password_hash = first.password_hash
            out = [f"line vty {start} {end}"]
            if line.exec_timeout != 600:
                m, s = divmod(line.exec_timeout, 60)
                out.append(f" exec-timeout {m} {s}")
            if line.login_local:
                out.append(" login local")
            elif line.login and line.password_hash:
                out.append(f" password 7 {line.password_hash[:14]}")
                out.append(" login")
            if line.logging_synchronous:
                out.append(" logging synchronous")
            if line.transport_input != ["all"]:
                out.append(f" transport input {' '.join(line.transport_input)}")
            out.append("!")
            return out
        # Individual lines
        result = []
        for v in self.vty_lines:
            result += self._render_line(v)
        return result
