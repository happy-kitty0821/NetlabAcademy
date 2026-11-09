"""
tests/test_cli.py
-----------------
Tests for the educational Cisco-style CLI (simulator_core.cli).

Covers: mode transitions, ping command, show commands, config commands,
invalid input, and unsupported command error format.
"""

from __future__ import annotations

import pytest
from tests.scenarios import build_sim
from simulator_core.cli import CLISession, CLIMode


def make_session(device_id: str = "host-a") -> CLISession:
    sim = build_sim(seed=42)
    return CLISession(device_id=device_id, simulation=sim)


# ── Mode transitions ──────────────────────────────────────────────────────────

class TestModeTransitions:
    def test_initial_mode_is_user_exec(self) -> None:
        s = make_session()
        assert s.mode == CLIMode.USER_EXEC

    def test_enable_enters_priv_exec(self) -> None:
        s = make_session()
        s.execute("enable")
        assert s.mode == CLIMode.PRIV_EXEC

    def test_disable_returns_to_user_exec(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("disable")
        assert s.mode == CLIMode.USER_EXEC

    def test_configure_terminal_enters_global_config(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        assert s.mode == CLIMode.GLOBAL_CONFIG

    def test_exit_from_global_returns_to_priv(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("exit")
        assert s.mode == CLIMode.PRIV_EXEC

    def test_interface_enters_iface_config(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("interface eth0")
        assert s.mode == CLIMode.IFACE_CONFIG
        assert s.current_iface == "eth0"

    def test_exit_from_iface_returns_to_global(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("interface eth0")
        s.execute("exit")
        assert s.mode == CLIMode.GLOBAL_CONFIG
        assert s.current_iface is None


# ── Prompts ───────────────────────────────────────────────────────────────────

class TestPrompts:
    def test_user_exec_prompt(self) -> None:
        s = make_session()
        assert s.prompt() == "PC-A>"

    def test_priv_exec_prompt(self) -> None:
        s = make_session()
        s.execute("enable")
        assert s.prompt() == "PC-A#"

    def test_global_config_prompt(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        assert s.prompt() == "PC-A(config)#"

    def test_hostname_change_updates_prompt(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("hostname Router1")
        assert s.prompt() == "Router1(config)#"


# ── Ping ──────────────────────────────────────────────────────────────────────

class TestPing:
    def test_ping_same_subnet_succeeds(self) -> None:
        s = make_session("host-a")
        output = s.execute("ping 192.168.1.2")
        assert "Success rate is 100 percent" in output
        assert "!!!!!" in output

    def test_ping_shows_cisco_format(self) -> None:
        s = make_session("host-a")
        output = s.execute("ping 192.168.1.2")
        assert "ICMP Echos to 192.168.1.2" in output
        assert "Type escape sequence to abort" in output

    def test_ping_invalid_ip(self) -> None:
        s = make_session("host-a")
        output = s.execute("ping notanip")
        assert "Bad IP" in output or "%" in output

    def test_ping_missing_ip(self) -> None:
        s = make_session("host-a")
        output = s.execute("ping")
        assert "%" in output

    def test_ping_repeat_flag(self) -> None:
        s = make_session("host-a")
        output = s.execute("ping 192.168.1.2 repeat 3")
        assert "(3/3)" in output or "3/" in output


# ── Show commands ─────────────────────────────────────────────────────────────

class TestShowCommands:
    def test_show_version(self) -> None:
        s = make_session()
        output = s.execute("show version")
        assert "NetLab Academy" in output
        assert "simulator-core" in output.lower() or "0.1.0" in output

    def test_show_ip_interface_brief(self) -> None:
        s = make_session()
        s.execute("enable")
        output = s.execute("show ip interface brief")
        assert "eth0" in output
        assert "192.168.1.1" in output

    def test_show_interfaces(self) -> None:
        s = make_session()
        s.execute("enable")
        output = s.execute("show interfaces")
        assert "eth0" in output
        assert "up" in output.lower()

    def test_show_arp_empty_initially(self) -> None:
        s = make_session()
        s.execute("enable")
        output = s.execute("show arp")
        # Should either be empty or show the ARP table header
        assert "Protocol" in output or "empty" in output.lower()

    def test_show_arp_populated_after_ping(self) -> None:
        s = make_session("host-a")
        s.execute("enable")
        s.execute("ping 192.168.1.2")
        output = s.execute("show arp")
        assert "192.168.1.2" in output

    def test_show_mac_on_switch(self) -> None:
        s = make_session("host-a")
        s.execute("ping 192.168.1.2")  # populate the MAC table

        sw_session = CLISession(
            device_id="switch-1",
            simulation=s.simulation,
        )
        sw_session.execute("enable")
        output = sw_session.execute("show mac address-table")
        assert "Mac Address Table" in output

    def test_show_running_config(self) -> None:
        s = make_session()
        s.execute("enable")
        output = s.execute("show running-config")
        assert "hostname" in output
        assert "interface eth0" in output


# ── Configuration commands ────────────────────────────────────────────────────

class TestConfigCommands:
    def test_ip_address_sets_ip(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("interface eth0")
        output = s.execute("ip address 10.0.0.1 255.255.255.0")
        assert output == "" or "%" not in output  # no error
        # Verify it's reflected in show
        s.execute("exit")
        s.execute("exit")
        brief = s.execute("show ip interface brief")
        assert "10.0.0.1" in brief

    def test_shutdown_marks_interface_down(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("interface eth0")
        s.execute("shutdown")
        s.execute("exit")
        s.execute("exit")
        brief = s.execute("show ip interface brief")
        assert "administratively down" in brief

    def test_no_shutdown_marks_interface_up(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("interface eth0")
        s.execute("shutdown")
        s.execute("no shutdown")
        s.execute("exit")
        s.execute("exit")
        brief = s.execute("show ip interface brief")
        assert "administratively down" not in brief


# ── Invalid input ─────────────────────────────────────────────────────────────

class TestInvalidInput:
    def test_unknown_command_returns_cisco_error(self) -> None:
        s = make_session()
        output = s.execute("nonsense")
        assert "Invalid input detected" in output
        assert "^" in output

    def test_empty_input_returns_empty(self) -> None:
        s = make_session()
        output = s.execute("")
        assert output == ""

    def test_whitespace_only_returns_empty(self) -> None:
        s = make_session()
        output = s.execute("   ")
        assert output == ""

    def test_unknown_show_sub_gives_hint(self) -> None:
        s = make_session()
        s.execute("enable")
        output = s.execute("show blahblah")
        assert "%" in output

    def test_interface_nonexistent_gives_error(self) -> None:
        s = make_session()
        s.execute("enable")
        s.execute("configure terminal")
        output = s.execute("interface eth99")
        assert "%" in output or "Invalid" in output
