"""
tests/test_e2e_ios_behaviour.py
-------------------------------
End-to-end checks for IOS behaviours students rely on in CCNA labs,
driven through the CLI:

  1. Line protocol follows cabling and the peer port; shutdown is visible.
  2. Switch management SVI: ARP/ping to and from the switch.
  3. Router-on-a-stick (802.1Q subinterfaces).
  4. Privilege levels: enable password, console login, logout.
  5. startup-config (copy run start / write memory / erase).
  6. Address validation (masks, reserved ranges, overlaps).
  7. Command parsing details (line con 0, en, regex pipes, banners).
"""

from __future__ import annotations

import pytest

from simulator_core.cli import CLIMode
from simulator_core.events import FrameTransmit
from tests.test_e2e_labs import _build, _cli, _pc, _ping, _router, _session, _switch


# ---------------------------------------------------------------------------
# Topologies
# ---------------------------------------------------------------------------

def access_lab():
    """PC1 ─ Fa0/1 SW1 Fa0/23 ─ Gi0/0 R1; every other port unplugged."""
    sw = _switch("sw1")
    sw.supports_svi = True
    return _build(
        [_pc("pc1", "192.168.1.10/24", "192.168.1.1"), sw, _router("r1"),
         _pc("pc9", "10.9.9.10/24", "10.9.9.1")],
        [("pc1", "eth0", "sw1", "Fa0/1"), ("sw1", "Fa0/23", "r1", "Gi0/0"),
         ("r1", "Gi0/1", "pc9", "eth0")],
    )


def configure_access_router(sim) -> None:
    _cli(sim, "r1", "enable", "conf t",
         "int g0/0", "ip address 192.168.1.1 255.255.255.0",
         "int g0/1", "ip address 10.9.9.1 255.255.255.0", "end")


def roas_lab():
    """PC10 (VLAN 10) and PC20 (VLAN 20) ─ SW1 ═trunk═ R1 Gi0/0 (subinterfaces)."""
    sim = _build(
        [_pc("pc10", "192.168.10.10/24", "192.168.10.1"),
         _pc("pc20", "192.168.20.10/24", "192.168.20.1"),
         _switch("sw1"), _router("r1")],
        [("pc10", "eth0", "sw1", "Fa0/1"), ("pc20", "eth0", "sw1", "Fa0/2"),
         ("sw1", "Fa0/23", "r1", "Gi0/0")],
    )
    _cli(sim, "sw1", "enable", "conf t", "vlan 10", "vlan 20", "exit",
         "int fa0/1", "switchport mode access", "switchport access vlan 10",
         "int fa0/2", "switchport mode access", "switchport access vlan 20",
         "int fa0/23", "switchport mode trunk", "end")
    _cli(sim, "r1", "enable", "conf t",
         "int g0/0.10", "encapsulation dot1Q 10", "ip address 192.168.10.1 255.255.255.0",
         "int g0/0.20", "encapsulation dot1Q 20", "ip address 192.168.20.1 255.255.255.0",
         "end")
    return sim


def brief_line(sim, dev: str, iface: str) -> str:
    out = _cli(sim, dev, "show ip interface brief")[0]
    return next(l for l in out.splitlines() if l.startswith(iface + " "))


# ---------------------------------------------------------------------------
# 1. Line protocol
# ---------------------------------------------------------------------------

class TestLineProtocol:
    def test_unplugged_switch_port_is_down(self) -> None:
        sim = access_lab()
        _cli(sim, "sw1", "enable")
        assert brief_line(sim, "sw1", "Fa0/1").split()[-2:] == ["up", "up"]
        assert brief_line(sim, "sw1", "Fa0/5").split()[-2:] == ["down", "down"]
        status = _cli(sim, "sw1", "show interfaces status")[0]
        assert any(l.startswith("Fa0/1 ") and "connected" in l for l in status.splitlines())
        assert any(l.startswith("Fa0/5 ") and "notconnect" in l for l in status.splitlines())

    def test_shutdown_shows_disabled_and_takes_peer_down(self) -> None:
        sim = access_lab()
        _cli(sim, "sw1", "enable", "conf t", "int fa0/23", "shutdown", "end")
        assert "administratively down down" in brief_line(sim, "sw1", "Fa0/23")
        status = _cli(sim, "sw1", "show interfaces status")[0]
        assert any(l.startswith("Fa0/23") and "disabled" in l for l in status.splitlines())
        # The router's port is still enabled, but its line protocol is down.
        configure_access_router(sim)
        assert brief_line(sim, "r1", "Gi0/0").split()[-2:] == ["down", "down"]

    def test_connected_route_needs_line_protocol(self) -> None:
        sim = access_lab()
        configure_access_router(sim)
        assert "192.168.1.0/24" in _cli(sim, "r1", "show ip route")[0]
        _cli(sim, "sw1", "enable", "conf t", "int fa0/23", "shutdown", "end")
        assert "192.168.1.0/24" not in _cli(sim, "r1", "show ip route")[0]
        _cli(sim, "sw1", "conf t", "int fa0/23", "no shutdown", "end")
        assert "192.168.1.0/24" in _cli(sim, "r1", "show ip route")[0]

    def test_link_removal_takes_ports_down(self) -> None:
        sim = access_lab()
        configure_access_router(sim)
        link = sim.topology.get_link("sw1", "Fa0/23")
        sim.remove_link(link.id)
        assert brief_line(sim, "r1", "Gi0/0").split()[-2:] == ["down", "down"]
        assert "192.168.1.0/24" not in _cli(sim, "r1", "show ip route")[0]

    def test_spanning_tree_lists_only_up_ports(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "show spanning-tree")[1]
        assert "\nFa0/1 " in out and "\nFa0/23 " in out
        assert "\nFa0/5 " not in out


# ---------------------------------------------------------------------------
# 2. Switch management SVI
# ---------------------------------------------------------------------------

class TestSwitchManagement:
    def _with_svi(self, gateway: bool = True):
        sim = access_lab()
        configure_access_router(sim)
        cmds = ["enable", "conf t", "interface vlan 1",
                "ip address 192.168.1.2 255.255.255.0", "no shutdown", "exit"]
        if gateway:
            cmds.append("ip default-gateway 192.168.1.1")
        _cli(sim, "sw1", *cmds, "end")
        return sim

    def test_new_vlan1_svi_starts_shutdown(self) -> None:
        sim = access_lab()
        _cli(sim, "sw1", "enable", "conf t", "interface vlan 1",
             "ip address 192.168.1.2 255.255.255.0", "end")
        assert "administratively down" in brief_line(sim, "sw1", "Vlan1")
        assert _ping(sim, "pc1", "192.168.1.2") == "....."

    def test_pc_pings_switch_svi(self) -> None:
        sim = self._with_svi()
        assert brief_line(sim, "sw1", "Vlan1").split()[-2:] == ["up", "up"]
        assert _ping(sim, "pc1", "192.168.1.2") == "!!!!!"

    def test_switch_pings_local_host(self) -> None:
        sim = self._with_svi()
        assert _ping(sim, "sw1", "192.168.1.10") == ".!!!!"
        assert _ping(sim, "sw1", "192.168.1.10") == "!!!!!"

    def test_remote_subnet_needs_default_gateway(self) -> None:
        sim = self._with_svi(gateway=False)
        out = _cli(sim, "sw1", "ping 10.9.9.10")[0]
        assert "....." in out and "ip default-gateway" in out
        _cli(sim, "sw1", "conf t", "ip default-gateway 192.168.1.1", "end")
        _ping(sim, "sw1", "10.9.9.10")
        assert _ping(sim, "sw1", "10.9.9.10") == "!!!!!"
        assert _ping(sim, "pc9", "192.168.1.2") == "!!!!!"

    def test_svi_down_without_active_vlan_ports(self) -> None:
        sim = access_lab()
        _cli(sim, "sw1", "enable", "conf t", "vlan 50", "exit",
             "interface vlan 50", "ip address 10.50.0.2 255.255.255.0", "no shutdown", "end")
        assert brief_line(sim, "sw1", "Vlan50").split()[-2:] == ["down", "down"]

    def test_show_arp_on_switch(self) -> None:
        sim = self._with_svi()
        _ping(sim, "pc1", "192.168.1.2")
        out = _cli(sim, "sw1", "show arp")[0]
        assert "192.168.1.2" in out and "192.168.1.10" in out and "Vlan1" in out


# ---------------------------------------------------------------------------
# 3. Router-on-a-stick
# ---------------------------------------------------------------------------

class TestRouterOnAStick:
    def test_inter_vlan_ping_through_subinterfaces(self) -> None:
        sim = roas_lab()
        assert _ping(sim, "pc10", "192.168.20.10") == "!!!!!"
        assert _ping(sim, "pc20", "192.168.10.1") == "!!!!!"

    def test_router_sends_tagged_frames_on_parent(self) -> None:
        sim = roas_lab()
        _ping(sim, "pc10", "192.168.20.10")
        tags = {e.frame.vlan_tag for e in sim.trace
                if isinstance(e, FrameTransmit) and e.device_id == "r1"}
        assert tags == {10, 20}
        assert not [e for e in sim.trace if isinstance(e, FrameTransmit)
                    and e.device_id == "r1" and "." in e.interface_name]

    def test_connected_routes_on_subinterfaces(self) -> None:
        sim = roas_lab()
        out = _cli(sim, "r1", "show ip route")[0]
        assert "192.168.10.0/24 is directly connected, Gi0/0.10" in out
        assert "192.168.20.0/24 is directly connected, Gi0/0.20" in out

    def test_ip_address_requires_encapsulation_first(self) -> None:
        sim = roas_lab()
        out = _cli(sim, "r1", "conf t", "int g0/0.30", "ip address 192.168.30.1 255.255.255.0")[2]
        assert "only allowed if that\nsubinterface is already configured" in out
        assert sim.topology.devices["r1"].interfaces["Gi0/0.30"].ip_config is None

    def test_duplicate_vlan_and_main_interface_encapsulation_rejected(self) -> None:
        sim = roas_lab()
        out = _cli(sim, "r1", "conf t", "int g0/0.30", "encapsulation dot1Q 10",
                   "int g0/0", "encapsulation dot1Q 30")
        assert "already configured on Gi0/0.10" in out[2]
        assert "main interface is not supported" in out[4]

    def test_subinterface_follows_parent_shutdown(self) -> None:
        sim = roas_lab()
        _cli(sim, "r1", "conf t", "int g0/0", "shutdown", "end")
        assert brief_line(sim, "r1", "Gi0/0.10").split()[-2:] == ["down", "down"]
        assert _ping(sim, "pc10", "192.168.20.10") == "....."

    def test_running_config_shows_subinterfaces(self) -> None:
        sim = roas_lab()
        out = _cli(sim, "r1", "show running-config")[0]
        assert "interface Gi0/0.10\n encapsulation dot1Q 10\n ip address 192.168.10.1 255.255.255.0" in out
        assert "switchport" not in out

    def test_native_vlan_subinterface_uses_untagged_frames(self) -> None:
        sim = _build(
            [_pc("pc1", "192.168.1.10/24", "192.168.1.1"), _switch("sw1"), _router("r1")],
            [("pc1", "eth0", "sw1", "Fa0/1"), ("sw1", "Fa0/23", "r1", "Gi0/0")],
        )
        _cli(sim, "sw1", "enable", "conf t", "int fa0/23", "switchport mode trunk", "end")
        _cli(sim, "r1", "enable", "conf t", "int g0/0.1", "encapsulation dot1Q 1 native",
             "ip address 192.168.1.1 255.255.255.0", "end")
        assert _ping(sim, "pc1", "192.168.1.1") == "!!!!!"


# ---------------------------------------------------------------------------
# 4. Privilege levels and login
# ---------------------------------------------------------------------------

class TestPrivilegeAndLogin:
    def test_show_running_config_needs_privileged_mode(self) -> None:
        sim = access_lab()
        assert _cli(sim, "sw1", "show running-config")[0].startswith("% Invalid input")
        assert "Interface" in _cli(sim, "sw1", "show ip interface brief")[0]

    def test_enable_asks_for_secret(self) -> None:
        sim = access_lab()
        _cli(sim, "sw1", "enable", "conf t", "enable secret class", "end", "disable")
        s = _session(sim, "sw1")
        assert s.execute("enable") == ""
        assert s.prompt() == "Password: " and s.input_hidden
        s.execute("wrong")
        assert s.prompt() == "Password: "
        s.execute("class")
        assert s.mode == CLIMode.PRIV_EXEC and not s.input_hidden

    def test_three_bad_enable_passwords(self) -> None:
        sim = access_lab()
        _cli(sim, "sw1", "enable", "conf t", "enable password cisco", "end", "disable")
        out = _cli(sim, "sw1", "enable", "a", "b", "c")
        assert "% Bad secrets" in out[-1]
        assert _session(sim, "sw1").mode == CLIMode.USER_EXEC

    def test_exit_ends_session_and_console_login_applies(self) -> None:
        sim = access_lab()
        _cli(sim, "sw1", "enable", "conf t", "banner motd #Authorized only#",
             "line con 0", "password cisco", "login", "end")
        s = _session(sim, "sw1")
        assert "Press RETURN to get started." in s.execute("exit")
        greeting = s.execute("")
        assert "Authorized only" in greeting and "#" not in greeting
        assert "User Access Verification" in greeting
        assert s.prompt() == "Password: "
        s.execute("cisco")
        assert s.mode == CLIMode.USER_EXEC and s.prompt().endswith(">")

    def test_login_local_with_privilege_15(self) -> None:
        sim = access_lab()
        _cli(sim, "sw1", "enable", "conf t", "username admin privilege 15 secret pass",
             "line console 0", "login local", "end")
        s = _session(sim, "sw1")
        s.execute("logout")
        s.execute("")
        assert s.prompt() == "Username: "
        s.execute("admin")
        assert s.prompt() == "Password: "
        s.execute("pass")
        assert s.mode == CLIMode.PRIV_EXEC

    def test_running_config_shows_enable_password_and_secret(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "conf t", "enable secret class",
                   "enable password cisco", "do show running-config")[-1]
        assert "enable secret 5 " in out
        assert "enable password cisco" in out
        out = _cli(sim, "sw1", "service password-encryption", "do show running-config")[-1]
        assert "enable password 7 " in out and "enable password cisco" not in out


# ---------------------------------------------------------------------------
# 5. startup-config
# ---------------------------------------------------------------------------

class TestStartupConfig:
    def test_copy_run_start_and_show_startup(self) -> None:
        sim = access_lab()
        s = _session(sim, "sw1")
        s.execute("enable")
        assert s.execute("show startup-config") == "startup-config is not present"
        s.execute("conf t")
        s.execute("hostname CORE1")
        s.execute("end")
        assert s.execute("copy running-config startup-config") == ""
        assert s.prompt() == "Destination filename [startup-config]? "
        assert s.execute("") == "Building configuration...\n[OK]"
        out = s.execute("show startup-config")
        assert out.startswith("Using ") and "hostname CORE1" in out

    def test_write_memory_and_erase(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "write memory", "show startup-config",
                   "erase startup-config", "show startup-config")
        assert out[1] == "Building configuration...\n[OK]"
        assert "hostname" in out[2]
        assert out[4] == "startup-config is not present"


# ---------------------------------------------------------------------------
# 6. Address validation
# ---------------------------------------------------------------------------

class TestAddressValidation:
    @pytest.mark.parametrize("cmd, expected", [
        ("ip address 10.1.1.1 255.0.255.0", "% Bad mask 0xFF00FF00 for address 10.1.1.1"),
        ("ip address 127.0.0.1 255.0.0.0", "Not a valid host address - 127.0.0.1"),
        ("ip address 224.0.0.1 255.255.255.0", "Not a valid host address - 224.0.0.1"),
        ("ip address 0.1.2.3 255.0.0.0", "Not a valid host address - 0.1.2.3"),
    ])
    def test_invalid_addresses_rejected(self, cmd: str, expected: str) -> None:
        sim = access_lab()
        out = _cli(sim, "r1", "enable", "conf t", "int g0/2", cmd)[-1]
        assert out == expected
        assert sim.topology.devices["r1"].interfaces["Gi0/2"].ip_config is None

    def test_prefix_length_form_rejected(self) -> None:
        sim = access_lab()
        out = _cli(sim, "r1", "enable", "conf t", "int g0/2", "ip address 10.1.1.1 24")[-1]
        assert out.startswith("% Invalid input")

    def test_overlapping_subnet_rejected(self) -> None:
        sim = access_lab()
        configure_access_router(sim)
        out = _cli(sim, "r1", "conf t", "int g0/2", "ip address 192.168.1.5 255.255.255.0")[-1]
        assert out == "% 192.168.1.0 overlaps with Gi0/0"

    def test_readdressing_same_interface_is_not_an_overlap(self) -> None:
        sim = access_lab()
        configure_access_router(sim)
        assert _cli(sim, "r1", "conf t", "int g0/0", "ip address 192.168.1.254 255.255.255.0")[-1] == ""

    def test_static_route_with_host_bits_rejected(self) -> None:
        sim = access_lab()
        configure_access_router(sim)
        out = _cli(sim, "r1", "conf t", "ip route 10.5.5.1 255.255.255.0 192.168.1.254")[-1]
        assert out == "%Inconsistent address and mask"


# ---------------------------------------------------------------------------
# 7. Parsing details
# ---------------------------------------------------------------------------

class TestParsing:
    def test_en_is_enable_in_privileged_mode(self) -> None:
        sim = access_lab()
        assert _cli(sim, "sw1", "en", "en")[1] == ""
        assert _session(sim, "sw1").mode == CLIMode.PRIV_EXEC

    @pytest.mark.parametrize("cmd, line", [
        ("line con 0", "console 0"),
        ("line console 0", "console 0"),
        ("line vty 0 15", "vty 0 15"),
        ("line v 5 15", "vty 5 15"),
    ])
    def test_line_abbreviations(self, cmd: str, line: str) -> None:
        sim = access_lab()
        s = _session(sim, "sw1")
        s.execute("enable")
        s.execute("conf t")
        assert s.execute(cmd) == ""
        assert s.mode == CLIMode.LINE_CONFIG and s.current_line == line

    def test_invalid_line_numbers(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "conf t", "line vty 0 16", "line con 1")
        assert out[2].startswith("% Invalid input") and out[3].startswith("% Invalid input")

    def test_vty_lines_grouped_in_running_config(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "conf t", "line vty 0 4", "login local",
                   "do show running-config")[-1]
        assert "line vty 0 4\n login local" in out
        assert "line vty 5 15" in out

    def test_include_accepts_regular_expression(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "show ip interface brief | include Fa0/1 |Fa0/23")[1]
        names = [l.split()[0] for l in out.splitlines()]
        assert names == ["Fa0/1", "Fa0/23"]
