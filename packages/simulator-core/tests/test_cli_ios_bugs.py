"""
tests/test_cli_ios_bugs.py
--------------------------
Regression tests for the Cisco IOS CLI behaviour bugs fixed in this sprint:

  Bug 1 — SVI accepts Layer 2 switchport commands (should reject)
  Bug 2 — show interfaces trunk lists SVIs (should exclude them)
  Bug 3 — 'end' from USER_EXEC elevates to PRIV_EXEC (should be no-op)
  Bug 4 — show ip interface brief accuracy

Each test class targets one bug. All tests are deterministic and use the
standard scenario helpers from tests.scenarios.
"""

from __future__ import annotations

import pytest

from tests.scenarios import build_sim
from simulator_core.cli import CLISession, CLIMode
from simulator_core.topology import Interface
from simulator_core.addresses import MACAddress
import random


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def switch_session() -> CLISession:
    """Return a CLISession attached to SW1 at GLOBAL_CONFIG."""
    sim = build_sim(seed=42)
    s = CLISession(device_id="switch-1", simulation=sim)
    s.execute("enable")
    s.execute("configure terminal")
    return s


def priv_switch_session() -> CLISession:
    """Return a CLISession attached to SW1 at PRIV_EXEC."""
    sim = build_sim(seed=42)
    s = CLISession(device_id="switch-1", simulation=sim)
    s.execute("enable")
    return s


def svi_capable_switch_session() -> CLISession:
    """
    Return a CLISession for SW1 with supports_svi=True at GLOBAL_CONFIG.

    Used to test SVI-specific behaviour (switchport rejection on SVIs,
    show ip int brief with SVIs) on a device that actually supports SVIs.
    A pure L2 switch does not support SVIs, so these tests require a
    device that explicitly has the capability flag set.
    """
    sim = build_sim(seed=42)
    # Enable SVI capability so we can enter interface vlan N
    sim.topology.devices["switch-1"].supports_svi = True
    s = CLISession(device_id="switch-1", simulation=sim)
    s.execute("enable")
    s.execute("configure terminal")
    return s


# ---------------------------------------------------------------------------
# Bug 1 — SVI must reject switchport commands
# ---------------------------------------------------------------------------

class TestSVISwitchportRejection:
    """
    interface vlan N is a Switch Virtual Interface — a Layer 3 logical
    interface.  It must NOT accept any Layer 2 switchport commands.
    """

    def _enter_svi(self) -> CLISession:
        s = svi_capable_switch_session()
        # First create the VLAN so the SVI is valid
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("interface vlan 10")
        assert s.mode == CLIMode.IFACE_CONFIG, (
            f"Expected IFACE_CONFIG after 'interface vlan 10' on SVI-capable device, got {s.mode}"
        )
        assert s.current_iface == "Vlan10"
        return s

    def test_svi_rejects_switchport_mode_trunk(self) -> None:
        s = self._enter_svi()
        out = s.execute("switchport mode trunk")
        assert "Invalid input" in out or "do not support" in out, (
            f"Expected rejection, got: {out!r}"
        )

    def test_svi_rejects_switchport_mode_access(self) -> None:
        s = self._enter_svi()
        out = s.execute("switchport mode access")
        assert "Invalid input" in out or "do not support" in out

    def test_svi_rejects_switchport_trunk_encapsulation(self) -> None:
        s = self._enter_svi()
        out = s.execute("switchport trunk encapsulation dot1q")
        assert "Invalid input" in out or "do not support" in out

    def test_svi_rejects_switchport_access_vlan(self) -> None:
        s = self._enter_svi()
        out = s.execute("switchport access vlan 10")
        assert "Invalid input" in out or "do not support" in out

    def test_svi_rejects_switchport_trunk_allowed_vlan(self) -> None:
        s = self._enter_svi()
        out = s.execute("switchport trunk allowed vlan 10,20")
        assert "Invalid input" in out or "do not support" in out

    def test_svi_switchport_mode_not_persisted_as_trunk(self) -> None:
        """
        Even if someone bypasses the CLI, the SVI must not end up in the
        trunk output.  Here we verify that the rejection prevents the state
        mutation.
        """
        s = self._enter_svi()
        sim = s.simulation
        # Attempt via CLI — should be rejected
        s.execute("switchport mode trunk")
        # The interface must NOT have been mutated to trunk
        iface = sim.topology.devices["switch-1"].interfaces.get("Vlan10")
        assert iface is not None
        # switchport_mode should still be "access" (the default for SVIs —
        # or at minimum NOT "trunk" after a rejected command)
        assert iface.switchport_mode != "trunk", (
            "SVI switchport_mode was set to 'trunk' despite CLI rejection"
        )

    def test_physical_interface_still_accepts_switchport_trunk(self) -> None:
        """Physical interfaces must NOT be broken by the SVI guard."""
        s = switch_session()
        s.execute("interface Gi0/0")
        out = s.execute("switchport mode trunk")
        assert "Invalid" not in out and "do not support" not in out, (
            f"Physical interface was incorrectly rejected: {out!r}"
        )
        iface = s.simulation.topology.devices["switch-1"].interfaces["Gi0/0"]
        assert iface.switchport_mode == "trunk"

    def test_physical_interface_accepts_switchport_access(self) -> None:
        s = switch_session()
        s.execute("interface Gi0/1")
        out = s.execute("switchport mode access")
        assert "Invalid" not in out and "do not support" not in out
        iface = s.simulation.topology.devices["switch-1"].interfaces["Gi0/1"]
        assert iface.switchport_mode == "access"


# ---------------------------------------------------------------------------
# Bug 2 — show interfaces trunk must exclude SVIs
# ---------------------------------------------------------------------------

class TestShowInterfacesTrunkExcludesSVI:
    """
    show interfaces trunk must only list physical Layer 2 trunk ports.
    SVIs must never appear in this output regardless of their
    switchport_mode field value.
    """

    def test_no_trunks_returns_empty_message(self) -> None:
        s = priv_switch_session()
        out = s.execute("show interfaces trunk")
        assert "No trunk" in out

    def test_physical_trunk_appears(self) -> None:
        s = switch_session()
        s.execute("interface Gi0/0")
        s.execute("switchport mode trunk")
        s.execute("end")
        out = s.execute("show interfaces trunk")
        assert "Gi0/0" in out

    def test_svi_never_appears_in_trunk_output(self) -> None:
        """
        Force-set an SVI's switchport_mode directly (bypassing CLI) and
        verify that show interfaces trunk still excludes it.  This tests
        the display filter, not just the CLI guard.
        """
        sim = build_sim(seed=42)
        sw = sim.topology.devices["switch-1"]
        # Add a Vlan10 SVI directly
        svi = Interface(
            name="Vlan10",
            mac=MACAddress.generate(random.Random(99)),
        )
        # Force trunk mode directly on the SVI (bypasses CLI guard intentionally
        # to test the display filter independently)
        svi.switchport_mode = "trunk"
        sw.add_interface(svi)

        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        out = s.execute("show interfaces trunk")
        assert "Vlan10" not in out, (
            f"SVI Vlan10 appeared in 'show interfaces trunk': {out!r}"
        )

    def test_svi_in_trunk_output_while_physical_trunk_present(self) -> None:
        """
        When a physical trunk exists AND an SVI has trunk mode forced,
        only the physical trunk must appear.
        """
        sim = build_sim(seed=42)
        sw = sim.topology.devices["switch-1"]

        # Set Gi0/0 as trunk via CLI
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("interface Gi0/0")
        s.execute("switchport mode trunk")
        s.execute("end")

        # Force-add an SVI with trunk mode (bypasses CLI to test display filter)
        svi = Interface(name="Vlan10", mac=MACAddress.generate(random.Random(99)))
        svi.switchport_mode = "trunk"
        sw.add_interface(svi)

        out = s.execute("show interfaces trunk")
        assert "Gi0/0" in out,     f"Physical trunk Gi0/0 missing from output: {out!r}"
        assert "Vlan10" not in out, f"SVI Vlan10 leaked into trunk output: {out!r}"


# ---------------------------------------------------------------------------
# Bug 3 — CLI mode transitions
# ---------------------------------------------------------------------------

class TestCLIModeTransitions:
    """
    Test the full CLI mode state machine.
    Key regression: 'end' from USER_EXEC must NOT elevate to PRIV_EXEC.
    """

    # ── end from every config mode → PRIV_EXEC ───────────────────────────────

    def test_end_from_iface_config_returns_to_priv(self) -> None:
        s = switch_session()
        s.execute("interface Gi0/0")
        assert s.mode == CLIMode.IFACE_CONFIG
        s.execute("end")
        assert s.mode == CLIMode.PRIV_EXEC

    def test_end_from_vlan_config_returns_to_priv(self) -> None:
        s = switch_session()
        s.execute("vlan 10")
        assert s.mode == CLIMode.VLAN_CONFIG
        s.execute("end")
        assert s.mode == CLIMode.PRIV_EXEC

    def test_end_from_global_config_returns_to_priv(self) -> None:
        s = switch_session()
        assert s.mode == CLIMode.GLOBAL_CONFIG
        s.execute("end")
        assert s.mode == CLIMode.PRIV_EXEC

    def test_end_from_priv_exec_is_noop(self) -> None:
        """'end' in PRIV_EXEC must not change mode."""
        s = switch_session()
        s.execute("end")  # → PRIV_EXEC
        assert s.mode == CLIMode.PRIV_EXEC
        s.execute("end")  # should remain PRIV_EXEC
        assert s.mode == CLIMode.PRIV_EXEC

    def test_end_from_user_exec_does_not_elevate(self) -> None:
        """
        REGRESSION: 'end' from USER_EXEC must NOT elevate to PRIV_EXEC.
        Before the fix, _cmd_end() unconditionally set PRIV_EXEC for 'end'.
        """
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        assert s.mode == CLIMode.USER_EXEC
        s.execute("end")
        assert s.mode == CLIMode.USER_EXEC, (
            f"'end' in USER_EXEC elevated to {s.mode!r}; must remain USER_EXEC"
        )

    # ── exit transitions ──────────────────────────────────────────────────────

    def test_exit_from_iface_config_returns_to_global(self) -> None:
        s = switch_session()
        s.execute("interface Gi0/0")
        s.execute("exit")
        assert s.mode == CLIMode.GLOBAL_CONFIG
        assert s.current_iface is None

    def test_exit_from_vlan_config_returns_to_global(self) -> None:
        s = switch_session()
        s.execute("vlan 10")
        s.execute("exit")
        assert s.mode == CLIMode.GLOBAL_CONFIG
        assert s.current_vlan is None

    def test_exit_from_global_config_returns_to_priv(self) -> None:
        s = switch_session()
        s.execute("exit")
        assert s.mode == CLIMode.PRIV_EXEC

    def test_exit_from_priv_exec_returns_to_user(self) -> None:
        s = switch_session()
        s.execute("end")  # → PRIV_EXEC
        s.execute("exit")
        assert s.mode == CLIMode.USER_EXEC

    # ── invalid commands do not change mode ───────────────────────────────────

    def test_invalid_command_does_not_change_mode(self) -> None:
        s = switch_session()
        assert s.mode == CLIMode.GLOBAL_CONFIG
        s.execute("totally-invalid-command-xyz")
        assert s.mode == CLIMode.GLOBAL_CONFIG

    def test_invalid_command_in_priv_exec_does_not_change_mode(self) -> None:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        assert s.mode == CLIMode.PRIV_EXEC
        s.execute("gibberish-command")
        assert s.mode == CLIMode.PRIV_EXEC

    # ── empty input does not change mode ─────────────────────────────────────

    def test_empty_input_does_not_change_mode(self) -> None:
        s = switch_session()
        s.execute("")
        assert s.mode == CLIMode.GLOBAL_CONFIG
        s.execute("   ")
        assert s.mode == CLIMode.GLOBAL_CONFIG

    # ── enable / disable ─────────────────────────────────────────────────────

    def test_enable_from_user_exec(self) -> None:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        assert s.mode == CLIMode.PRIV_EXEC

    def test_disable_from_priv_exec(self) -> None:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("disable")
        assert s.mode == CLIMode.USER_EXEC

    # ── stale context is cleared on mode transitions ──────────────────────────

    def test_exit_from_iface_clears_current_iface(self) -> None:
        s = switch_session()
        s.execute("interface Gi0/0")
        assert s.current_iface == "Gi0/0"
        s.execute("exit")
        assert s.current_iface is None

    def test_end_from_iface_clears_current_iface(self) -> None:
        s = switch_session()
        s.execute("interface Gi0/0")
        s.execute("end")
        assert s.current_iface is None

    def test_exit_from_vlan_clears_current_vlan(self) -> None:
        s = switch_session()
        s.execute("vlan 10")
        s.execute("exit")
        assert s.current_vlan is None

    def test_end_from_vlan_clears_current_vlan(self) -> None:
        s = switch_session()
        s.execute("vlan 10")
        s.execute("end")
        assert s.current_vlan is None


# ---------------------------------------------------------------------------
# Bug 4 — show ip interface brief accuracy
# ---------------------------------------------------------------------------

class TestShowIpInterfaceBrief:

    def test_physical_no_ip_shows_unassigned(self) -> None:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        out = s.execute("show ip interface brief")
        # Gi0/0 has no IP address configured — must show "unassigned"
        assert "unassigned" in out

    def test_physical_up_shows_up_up(self) -> None:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        out = s.execute("show ip interface brief")
        # Both Gi0/0 and Gi0/1 are UP by default
        lines = {line.split()[0]: line for line in out.splitlines()[1:] if line.strip()}
        assert "up" in lines.get("Gi0/0", "").lower()
        assert "up" in lines.get("Gi0/1", "").lower()

    def test_admin_down_interface_shows_administratively_down(self) -> None:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("interface Gi0/0")
        s.execute("shutdown")
        s.execute("end")
        out = s.execute("show ip interface brief")
        # Gi0/0 must show "administratively down"
        gi00_line = next(
            (line for line in out.splitlines() if line.startswith("Gi0/0")), ""
        )
        assert "administratively down" in gi00_line, (
            f"Expected 'administratively down' in line: {gi00_line!r}"
        )

    def test_svi_appears_when_configured(self) -> None:
        """An SVI with an IP address must appear in show ip interface brief."""
        sim = build_sim(seed=42)
        sim.topology.devices["switch-1"].supports_svi = True  # enable SVI capability
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("interface vlan 10")
        s.execute("ip address 192.168.10.1 255.255.255.0")
        s.execute("no shutdown")
        s.execute("end")
        out = s.execute("show ip interface brief")
        assert "Vlan10" in out, f"SVI Vlan10 missing from show ip int brief: {out!r}"
        vlan_line = next(
            (line for line in out.splitlines() if line.startswith("Vlan10")), ""
        )
        assert "192.168.10.1" in vlan_line, (
            f"SVI IP missing from show ip int brief line: {vlan_line!r}"
        )

    def test_host_interface_shows_assigned_ip(self) -> None:
        """Host eth0 is configured with 192.168.1.1/24 — must appear."""
        sim = build_sim(seed=42)
        s = CLISession(device_id="host-a", simulation=sim)
        s.execute("enable")
        out = s.execute("show ip interface brief")
        eth0_line = next(
            (line for line in out.splitlines() if line.startswith("eth0")), ""
        )
        assert "192.168.1.1" in eth0_line, (
            f"Host IP missing from show ip int brief: {eth0_line!r}"
        )
        assert "unassigned" not in eth0_line


# ---------------------------------------------------------------------------
# Interface type classification unit tests
# ---------------------------------------------------------------------------

class TestInterfaceTypeClassification:
    """
    Unit tests for the is_svi, is_loopback, and is_physical_switchport
    properties added to topology.Interface.
    """

    def _make_iface(self, name: str) -> Interface:
        return Interface(name=name, mac=MACAddress.generate(random.Random(hash(name))))

    def test_vlan_interface_is_svi(self) -> None:
        assert self._make_iface("Vlan10").is_svi is True

    def test_vlan1_is_svi(self) -> None:
        assert self._make_iface("Vlan1").is_svi is True

    def test_gi_interface_is_not_svi(self) -> None:
        assert self._make_iface("Gi0/0").is_svi is False

    def test_eth_interface_is_not_svi(self) -> None:
        assert self._make_iface("eth0").is_svi is False

    def test_loopback_is_loopback(self) -> None:
        assert self._make_iface("Loopback0").is_loopback is True

    def test_gi_interface_is_physical_switchport(self) -> None:
        assert self._make_iface("Gi0/0").is_physical_switchport is True

    def test_fa_interface_is_physical_switchport(self) -> None:
        assert self._make_iface("Fa0/1").is_physical_switchport is True

    def test_svi_is_not_physical_switchport(self) -> None:
        assert self._make_iface("Vlan10").is_physical_switchport is False

    def test_loopback_is_not_physical_switchport(self) -> None:
        assert self._make_iface("Loopback0").is_physical_switchport is False


# ---------------------------------------------------------------------------
# Sprint 2 regression tests — username parsing, pipe filters, capability
# enforcement
# ---------------------------------------------------------------------------


class TestUsernameCommandParsing:
    """
    Regression tests for the username command tokenization and privilege
    level parsing.  The bug symptom was 'aayushprivilege' (concatenated
    name and keyword) and privilege reset to 1.
    """

    def _session(self) -> CLISession:
        s = switch_session()
        return s

    def test_username_privilege_15_stored_correctly(self) -> None:
        s = self._session()
        s.execute("username admin privilege 15 secret SecurePass1")
        device = s.simulation.topology.devices["switch-1"]
        user = device.config.users.get("admin")
        assert user is not None, "User 'admin' was not created"
        assert user.username == "admin", f"Username corrupted: {user.username!r}"
        assert user.privilege == 15, f"Privilege should be 15, got {user.privilege}"

    def test_username_privilege_1_stored_correctly(self) -> None:
        s = self._session()
        s.execute("username viewer privilege 1 secret pass")
        user = s.simulation.topology.devices["switch-1"].config.users.get("viewer")
        assert user is not None
        assert user.privilege == 1

    def test_username_privilege_0_stored_correctly(self) -> None:
        s = self._session()
        s.execute("username guest privilege 0 secret pass")
        user = s.simulation.topology.devices["switch-1"].config.users.get("guest")
        assert user is not None
        assert user.privilege == 0

    def test_username_privilege_5_stored_correctly(self) -> None:
        s = self._session()
        s.execute("username op privilege 5 secret pass")
        user = s.simulation.topology.devices["switch-1"].config.users.get("op")
        assert user is not None
        assert user.privilege == 5

    def test_username_default_privilege_is_1(self) -> None:
        s = self._session()
        s.execute("username nopriv secret pass")
        user = s.simulation.topology.devices["switch-1"].config.users.get("nopriv")
        assert user is not None
        assert user.privilege == 1

    def test_username_secret_is_hashed_not_plaintext(self) -> None:
        s = self._session()
        s.execute("username alice privilege 15 secret MySecret99")
        user = s.simulation.topology.devices["switch-1"].config.users.get("alice")
        assert user is not None
        assert "MySecret99" not in user.password_hash, (
            "Plaintext password must not be stored in password_hash"
        )
        assert len(user.password_hash) >= 16, "Hash too short"

    def test_username_in_running_config_has_correct_privilege(self) -> None:
        s = switch_session()
        s.execute("username bob privilege 15 secret BobPass1")
        s.execute("end")
        out = priv_switch_session.__class__  # just to confirm we can call priv session
        s2 = svi_capable_switch_session.__class__  # just checking import
        # Use same session at PRIV_EXEC
        sim = build_sim(seed=42)
        sess = CLISession(device_id="switch-1", simulation=sim)
        sess.execute("enable")
        sess.execute("configure terminal")
        sess.execute("username bob privilege 15 secret BobPass1")
        sess.execute("end")
        rc = sess.execute("show running-config")
        username_lines = [l for l in rc.splitlines() if "username" in l]
        assert len(username_lines) == 1
        line = username_lines[0]
        assert "bob" in line
        assert "privilege 15" in line, f"Privilege 15 missing from: {line!r}"
        assert "BobPass1" not in line, "Plaintext secret must not appear in running-config"

    def test_username_invalid_privilege_level_rejected(self) -> None:
        s = self._session()
        out = s.execute("username badpriv privilege 16 secret pass")
        assert "%" in out, "Should return an error for privilege > 15"
        user = s.simulation.topology.devices["switch-1"].config.users.get("badpriv")
        assert user is None, "User must not be created when privilege is invalid"

    def test_username_missing_secret_rejected(self) -> None:
        s = self._session()
        out = s.execute("username nopass privilege 15")
        assert "%" in out or "Incomplete" in out

    def test_username_config_round_trip(self) -> None:
        """Stored privilege must be the same value that appears in running-config."""
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("username charlie privilege 7 secret Pr1v7Pass")
        s.execute("end")
        rc = s.execute("show running-config")
        username_lines = [l for l in rc.splitlines() if "charlie" in l]
        assert len(username_lines) == 1
        assert "privilege 7" in username_lines[0], (
            f"Expected privilege 7 in running-config, got: {username_lines[0]!r}"
        )


class TestPipeFilters:
    """
    Test | include, | exclude, | section, and | begin filters.
    These must work both from PRIV_EXEC and from config mode via 'do'.
    """

    def _session_with_user(self) -> CLISession:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("username alice privilege 15 secret AlicePass1")
        s.execute("username bob privilege 1 secret BobPass2")
        s.execute("end")
        return s

    def test_pipe_include_from_priv_exec(self) -> None:
        s = self._session_with_user()
        out = s.execute("show running-config | include username")
        lines = [l for l in out.splitlines() if l.strip()]
        assert all("username" in l.lower() for l in lines), (
            f"include filter should only return lines containing 'username': {out!r}"
        )
        assert any("alice" in l for l in lines)
        assert any("bob" in l for l in lines)

    def test_pipe_include_from_global_config_via_do(self) -> None:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("username alice privilege 15 secret AlicePass1")
        out = s.execute("do show running-config | include username")
        # Must NOT return an invalid input error
        assert "Invalid input" not in out, (
            f"'do show running-config | include' should work from config mode: {out!r}"
        )
        lines = [l for l in out.splitlines() if l.strip()]
        assert any("alice" in l for l in lines), (
            f"Expected 'alice' in filtered output: {out!r}"
        )

    def test_pipe_exclude_removes_matching_lines(self) -> None:
        s = self._session_with_user()
        out = s.execute("show running-config | exclude username")
        assert "username" not in out.lower(), (
            f"exclude filter should remove all 'username' lines: {out!r}"
        )

    def test_pipe_include_no_match_returns_empty(self) -> None:
        s = self._session_with_user()
        out = s.execute("show running-config | include zzz_no_match_zzz")
        assert out.strip() == "", f"No matches should produce empty output, got: {out!r}"

    def test_pipe_begin_starts_from_first_match(self) -> None:
        s = self._session_with_user()
        out = s.execute("show running-config | begin hostname")
        lines = out.splitlines()
        assert lines[0].startswith("hostname") or "hostname" in lines[0], (
            f"begin filter should start from hostname line: {out!r}"
        )

    def test_pipe_do_include_hostname(self) -> None:
        sim = build_sim(seed=42)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        out = s.execute("do show running-config | include hostname")
        assert "Invalid input" not in out
        assert "hostname" in out.lower() or out.strip() == ""

    def test_pipe_include_case_insensitive(self) -> None:
        s = self._session_with_user()
        out_lower = s.execute("show running-config | include username")
        out_upper = s.execute("show running-config | include USERNAME")
        # Both should return the same set of lines
        assert out_lower == out_upper


class TestSVICapabilityEnforcement:
    """
    Tests for device capability enforcement on interface vlan N (SVI).

    A pure L2 switch (supports_svi=False) must reject 'interface vlan N'.
    A device with supports_svi=True must accept it.
    Speed/duplex commands on SVIs must be rejected.
    """

    def test_l2_switch_rejects_interface_vlan(self) -> None:
        """L2-only switch must not allow SVI creation."""
        sim = build_sim(seed=42)
        assert not sim.topology.devices["switch-1"].supports_svi, (
            "Test precondition: switch-1 must not have SVI capability"
        )
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        out = s.execute("interface vlan 10")
        assert "Invalid input" in out or "not supported" in out, (
            f"L2 switch should reject 'interface vlan 10': {out!r}"
        )
        # Mode must NOT have changed to IFACE_CONFIG
        assert s.mode == CLIMode.GLOBAL_CONFIG, (
            f"Mode should remain GLOBAL_CONFIG after rejection, got {s.mode}"
        )
        # No Vlan10 interface must have been created
        assert "Vlan10" not in sim.topology.devices["switch-1"].interfaces, (
            "Vlan10 interface must not be created on L2-only switch"
        )

    def test_svi_capable_device_accepts_interface_vlan(self) -> None:
        """Device with supports_svi=True must accept interface vlan N."""
        sim = build_sim(seed=42)
        sim.topology.devices["switch-1"].supports_svi = True
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        out = s.execute("interface vlan 10")
        assert "Invalid" not in out and "not supported" not in out, (
            f"SVI-capable device should accept 'interface vlan 10': {out!r}"
        )
        assert s.mode == CLIMode.IFACE_CONFIG
        assert s.current_iface == "Vlan10"

    def test_speed_command_rejected_on_svi(self) -> None:
        """'speed auto' must be rejected on an SVI."""
        sim = build_sim(seed=42)
        sim.topology.devices["switch-1"].supports_svi = True
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("interface vlan 10")
        out = s.execute("speed auto")
        assert "Invalid input" in out or "not supported" in out, (
            f"'speed auto' should be rejected on SVI: {out!r}"
        )

    def test_duplex_command_rejected_on_svi(self) -> None:
        """'duplex full' must be rejected on an SVI."""
        sim = build_sim(seed=42)
        sim.topology.devices["switch-1"].supports_svi = True
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("interface vlan 10")
        out = s.execute("duplex full")
        assert "Invalid input" in out or "not supported" in out, (
            f"'duplex full' should be rejected on SVI: {out!r}"
        )

    def test_speed_command_accepted_on_physical_interface(self) -> None:
        """'speed 100' must still work on a physical interface."""
        s = switch_session()
        s.execute("interface Gi0/0")
        out = s.execute("speed 100")
        assert "Invalid input" not in out and "not supported" not in out, (
            f"'speed 100' should be accepted on physical interface: {out!r}"
        )

    def test_svi_excluded_from_running_config_on_l2_switch(self) -> None:
        """
        If a Vlan interface exists on an L2 switch (from before capability
        check was enforced), it must not appear in show running-config.
        """
        from simulator_core.addresses import MACAddress
        import random as _rand
        sim = build_sim(seed=42)
        sw = sim.topology.devices["switch-1"]
        # Force-add SVI directly (bypasses CLI) to test display filter
        svi = Interface(name="Vlan10", mac=MACAddress.generate(_rand.Random(77)))
        sw.add_interface(svi)
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        rc = s.execute("show running-config")
        assert "Vlan10" not in rc, (
            f"SVI must not appear in running-config of L2-only switch: {rc!r}"
        )

    def test_svi_in_running_config_on_svi_capable_device(self) -> None:
        """SVI with IP must appear in running-config of SVI-capable device."""
        sim = build_sim(seed=42)
        sim.topology.devices["switch-1"].supports_svi = True
        s = CLISession(device_id="switch-1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("interface vlan 10")
        s.execute("ip address 192.168.10.1 255.255.255.0")
        s.execute("no shutdown")
        s.execute("end")
        rc = s.execute("show running-config")
        assert "Vlan10" in rc or "interface Vlan10" in rc, (
            f"SVI must appear in running-config of SVI-capable device: {rc!r}"
        )
