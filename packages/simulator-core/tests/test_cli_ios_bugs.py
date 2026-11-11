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


# ---------------------------------------------------------------------------
# Bug 1 — SVI must reject switchport commands
# ---------------------------------------------------------------------------

class TestSVISwitchportRejection:
    """
    interface vlan N is a Switch Virtual Interface — a Layer 3 logical
    interface.  It must NOT accept any Layer 2 switchport commands.
    """

    def _enter_svi(self) -> CLISession:
        s = switch_session()
        # First create the VLAN so the SVI is valid
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("interface vlan 10")
        assert s.mode == CLIMode.IFACE_CONFIG
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
