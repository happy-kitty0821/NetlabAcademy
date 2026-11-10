"""
tests/test_device_config.py
---------------------------
Tests for shared device configuration: users, enable secret, line config,
logging, service, banner — works on both switches and routers.
"""

from __future__ import annotations

import pytest
from tests.scenarios import build_sim
from simulator_core.cli import CLISession, CLIMode
from simulator_core.device_config import DeviceConfig, LogSeverity


def make_switch_session() -> CLISession:
    sim = build_sim(seed=42)
    s = CLISession(device_id="switch-1", simulation=sim)
    s.execute("enable")
    return s


def make_router_session() -> CLISession:
    """Build a topology with a router for router-specific tests."""
    import random
    from simulator_core.addresses import MACAddress
    from simulator_core.simulation import Simulation
    from simulator_core.topology import Device, Interface, Link, Topology
    from simulator_core.types import DeviceModel

    def _mac(seed):
        return MACAddress.generate(random.Random(seed))

    topo = Topology()
    r1 = Device(id="r1", model=DeviceModel.ROUTER, hostname="R1")
    r1.add_interface(Interface(name="Gi0/0", mac=_mac(1)))
    r1.interfaces["Gi0/0"].set_ip("192.168.1.1/24")
    topo.add_device(r1)
    topo.validate()
    sim = Simulation(topo, seed=42)
    s = CLISession(device_id="r1", simulation=sim)
    s.execute("enable")
    return s


# ── Enable secret / password ──────────────────────────────────────────────────


class TestEnableSecret:
    def test_set_enable_secret(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("enable secret MyPass123")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.enable_secret_hash is not None
        assert config.enable_auth_required is True

    def test_set_enable_password(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("enable password PlainPass")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.enable_password_hash is not None

    def test_no_enable_secret(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("enable secret MyPass123")
        s.execute("no enable secret")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.enable_secret_hash is None


# ── User accounts ─────────────────────────────────────────────────────────────


class TestUserAccounts:
    def test_create_user(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("username admin privilege 15 secret AdminPass")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert "admin" in config.users
        assert config.users["admin"].privilege == 15
        assert config.users["admin"].check_password("AdminPass") is True

    def test_create_user_default_privilege(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("username student secret StudentPass")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert "student" in config.users
        assert config.users["student"].privilege == 1

    def test_delete_user(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("username temp secret TempPass")
        s.execute("no username temp")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert "temp" not in config.users

    def test_user_password_verification(self) -> None:
        config = DeviceConfig()
        config.add_user("testuser", "mypassword", 5)
        assert config.check_user("testuser", "mypassword") is True
        assert config.check_user("testuser", "wrongpassword") is False
        assert config.check_user("nonexistent", "password") is False


# ── Line config ────────────────────────────────────────────────────────────────


class TestLineConfig:
    def test_enter_line_vty(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        assert s.mode == CLIMode.LINE_CONFIG
        assert s.current_line == "vty 0 4"

    def test_enter_line_console(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line console 0")
        assert s.mode == CLIMode.LINE_CONFIG
        assert s.current_line == "console 0"

    def test_line_login_local(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        s.execute("login local")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.vty_lines[0].login_local is True

    def test_line_password(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        s.execute("password MyLinePass")
        s.execute("login")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.vty_lines[0].password_hash is not None
        assert config.vty_lines[0].login is True

    def test_line_exec_timeout(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        s.execute("exec-timeout 5 30")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.vty_lines[0].exec_timeout == 330  # 5*60 + 30

    def test_line_logging_synchronous(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        s.execute("logging synchronous")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.vty_lines[0].logging_synchronous is True

    def test_line_transport_input(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        s.execute("transport input ssh")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.vty_lines[0].transport_input == ["ssh"]

    def test_exit_from_line_config(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        s.execute("exit")
        assert s.mode == CLIMode.GLOBAL_CONFIG
        assert s.current_line is None


# ── Logging ────────────────────────────────────────────────────────────────────


class TestLogging:
    def test_logging_buffered(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("logging buffered 8192 debugging")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.logging_buffered_size == 8192
        assert config.logging_buffered_level == LogSeverity.DEBUGGING

    def test_logging_console_level(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("logging console informational")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.logging_console_level == LogSeverity.INFORMATIONAL

    def test_logging_host(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("logging 192.168.1.100")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert "192.168.1.100" in config.logging_hosts

    def test_no_logging_host(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("logging 192.168.1.100")
        s.execute("no logging 192.168.1.100")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert "192.168.1.100" not in config.logging_hosts

    def test_add_log_entry(self) -> None:
        config = DeviceConfig()
        config.add_log(10, LogSeverity.WARNINGS, "SYS", "Test warning")
        assert len(config.log_buffer) == 1
        assert "Test warning" in str(config.log_buffer[0])

    def test_show_logging(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("logging buffered 4096 debugging")
        s.execute("end")
        out = s.execute("show logging")
        assert "Syslog logging" in out
        assert "4096" in out


# ── Service ────────────────────────────────────────────────────────────────────


class TestService:
    def test_service_password_encryption(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("service password-encryption")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.service_password_encryption is True

    def test_no_ip_domain_lookup(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("no ip domain-lookup")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.no_ip_domain_lookup is True

    def test_ip_domain_name(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("ip domain-name example.com")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert config.ip_domain_name == "example.com"


# ── Banner ────────────────────────────────────────────────────────────────────


class TestBanner:
    def test_banner_motd(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("banner motd Authorized access only")
        s.execute("end")
        config = s.simulation.topology.devices["switch-1"].config
        assert "Authorized access only" in config.banner_motd


# ── Show commands ──────────────────────────────────────────────────────────────


class TestShowConfig:
    def test_show_users(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("username admin privilege 15 secret AdminPass")
        s.execute("end")
        out = s.execute("show users")
        assert "admin" in out
        assert "privilege 15" in out

    def test_show_running_config_includes_users(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("username admin privilege 15 secret AdminPass")
        s.execute("enable secret EnableSecret")
        s.execute("service password-encryption")
        s.execute("no ip domain-lookup")
        s.execute("end")
        out = s.execute("show running-config")
        assert "username admin" in out
        assert "enable secret" in out
        assert "service password-encryption" in out
        assert "no ip domain-lookup" in out

    def test_show_running_config_includes_line_config(self) -> None:
        s = make_switch_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        s.execute("login local")
        s.execute("exec-timeout 5 30")
        s.execute("logging synchronous")
        s.execute("transport input ssh")
        s.execute("end")
        # make_switch_session already called enable; end returns to priv exec
        assert s.mode == CLIMode.PRIV_EXEC
        out = s.execute("show running-config")
        assert "line vty 0 4" in out
        assert "login local" in out
        assert "exec-timeout 5 30" in out
        assert "logging synchronous" in out
        assert "transport input ssh" in out


# ── Works on routers too ──────────────────────────────────────────────────────


class TestSharedConfigOnRouter:
    """Verify the same commands work on a router."""

    def test_enable_secret_on_router(self) -> None:
        s = make_router_session()
        s.execute("configure terminal")
        s.execute("enable secret RouterPass")
        s.execute("end")
        config = s.simulation.topology.devices["r1"].config
        assert config.enable_secret_hash is not None

    def test_username_on_router(self) -> None:
        s = make_router_session()
        s.execute("configure terminal")
        s.execute("username netadmin privilege 15 secret NetAdminPass")
        s.execute("end")
        config = s.simulation.topology.devices["r1"].config
        assert "netadmin" in config.users
        assert config.users["netadmin"].privilege == 15

    def test_line_vty_on_router(self) -> None:
        s = make_router_session()
        s.execute("configure terminal")
        s.execute("line vty 0 4")
        s.execute("login local")
        s.execute("transport input ssh")
        s.execute("end")
        config = s.simulation.topology.devices["r1"].config
        assert config.vty_lines[0].login_local is True
        assert config.vty_lines[0].transport_input == ["ssh"]

    def test_logging_on_router(self) -> None:
        s = make_router_session()
        s.execute("configure terminal")
        s.execute("logging buffered 8192 informational")
        s.execute("end")
        config = s.simulation.topology.devices["r1"].config
        assert config.logging_buffered_size == 8192

    def test_show_running_config_on_router(self) -> None:
        s = make_router_session()
        s.execute("configure terminal")
        s.execute("enable secret RSecret")
        s.execute("username admin privilege 15 secret AdminPass")
        s.execute("no ip domain-lookup")
        s.execute("end")
        out = s.execute("show running-config")
        assert "enable secret" in out
        assert "username admin" in out
        assert "no ip domain-lookup" in out
