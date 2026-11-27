"""
tests/test_e2e_ios_output.py
----------------------------
IOS output fidelity, checked end to end through the CLI:

  1. show ip route layout (L routes, classful subnet headers, filters,
     per-address lookup) and exit-interface static routes with proxy ARP.
  2. Full interface names where IOS uses them, short names elsewhere,
     Cisco dotted MAC addresses and IOS port order.
  3. Switch tables: show vlan, show interfaces status / switchport,
     show mac address-table (+ filters, clear).
  4. Spanning-tree protocol wording per mode.
  5. Error carets, word help, case-sensitive regex pipes.
  6. Small EXEC commands: configure prompt, terminal length, history, ping.
"""

from __future__ import annotations

import re

from simulator_core.cli import CLIMode
from tests.test_e2e_ios_behaviour import access_lab, configure_access_router, roas_lab
from tests.test_e2e_labs import _build, _cli, _pc, _ping, _router, _session, two_router_lab

DOTTED_MAC = re.compile(r"\b[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\b")


# ---------------------------------------------------------------------------
# 1. Routing table
# ---------------------------------------------------------------------------

class TestShowIpRoute:
    def test_local_routes_and_variably_subnetted_header(self) -> None:
        sim = two_router_lab()
        out = _cli(sim, "r1", "show ip route")[0]
        assert "      10.0.0.0/8 is variably subnetted, 5 subnets, 3 masks" in out
        assert "C        10.1.1.0/24 is directly connected, GigabitEthernet0/0" in out
        assert "L        10.1.1.1/32 is directly connected, GigabitEthernet0/0" in out
        assert "C        10.0.12.0/30 is directly connected, GigabitEthernet0/1" in out
        assert "S        10.3.3.0/24 [1/0] via 10.0.12.2" in out

    def test_default_route_listed_first_at_top_level(self) -> None:
        sim = two_router_lab()
        out = _cli(sim, "r1", "conf t", "ip route 0.0.0.0 0.0.0.0 10.0.12.2", "end", "show ip route")[-1]
        body = out.split("\n\n", 2)[2].splitlines()
        assert body[0] == "S*    0.0.0.0/0 [1/0] via 10.0.12.2"
        assert "Gateway of last resort is 10.0.12.2 to network 0.0.0.0" in out

    def test_single_mask_group_is_subnetted(self) -> None:
        sim = two_router_lab()
        _cli(sim, "r1", "conf t", "ip route 172.20.1.0 255.255.255.0 10.0.12.2",
             "ip route 172.20.2.0 255.255.255.0 10.0.12.2", "end")
        out = _cli(sim, "r1", "show ip route")[0]
        assert "      172.20.0.0/24 is subnetted, 2 subnets" in out

    def test_static_and_connected_filters(self) -> None:
        sim = two_router_lab()
        static = _cli(sim, "r1", "show ip route static")[0]
        assert "S        10.3.3.0/24" in static and "C  " not in static
        connected = _cli(sim, "r1", "show ip route connected")[0]
        assert "C        10.1.1.0/24" in connected and "S  " not in connected

    def test_route_lookup_for_an_address(self) -> None:
        sim = two_router_lab()
        out = _cli(sim, "r1", "show ip route 10.3.3.77")[0]
        assert out.startswith("Routing entry for 10.3.3.0/24")
        assert 'Known via "static", distance 1, metric 0' in out
        assert "  * 10.0.12.2" in out
        assert _cli(sim, "r1", "show ip route 8.8.8.8")[0] == "% Network not in table"


class TestExitInterfaceStaticRoutes:
    def test_exit_interface_route_works_through_proxy_arp(self) -> None:
        sim = two_router_lab()
        # Replace R2's next-hop route with an exit-interface route.
        _cli(sim, "r2", "conf t", "no ip route 10.1.1.0 255.255.255.0 10.0.12.1",
             "ip route 10.1.1.0 255.255.255.0 GigabitEthernet 0/1", "end")
        out = _cli(sim, "r2", "show ip route static")[0]
        assert "S        10.1.1.0/24 is directly connected, GigabitEthernet0/1" in out
        assert _ping(sim, "pca", "10.3.3.10") == "!!!!!"
        assert "ip route 10.1.1.0 255.255.255.0 GigabitEthernet0/1" in _cli(sim, "r2", "show running-config")[0]

    def test_interface_and_next_hop_form(self) -> None:
        sim = two_router_lab()
        _cli(sim, "r1", "conf t", "ip route 192.168.50.0 255.255.255.0 g0/1 10.0.12.2", "end")
        out = _cli(sim, "r1", "show ip route static")[0]
        assert "S        192.168.50.0 [1/0] via 10.0.12.2, GigabitEthernet0/1" not in out  # classful /24: top level
        assert "S     192.168.50.0/24 [1/0] via 10.0.12.2, GigabitEthernet0/1" in out

    def test_exit_interface_route_withdrawn_when_interface_down(self) -> None:
        sim = two_router_lab()
        _cli(sim, "r1", "conf t", "ip route 172.31.0.0 255.255.0.0 g0/1", "int g0/1", "shutdown", "end")
        assert "172.31.0.0" not in _cli(sim, "r1", "show ip route")[0]


# ---------------------------------------------------------------------------
# 2. Names, MACs, order
# ---------------------------------------------------------------------------

class TestNamesAndAddresses:
    def test_full_names_where_ios_uses_them(self) -> None:
        sim = roas_lab()
        brief = _cli(sim, "r1", "show ip interface brief")[0]
        names = [l.split()[0] for l in brief.splitlines()[1:]]
        # Subinterfaces follow their parent, in numeric order
        assert names[:4] == ["GigabitEthernet0/0", "GigabitEthernet0/0.10",
                             "GigabitEthernet0/0.20", "GigabitEthernet0/1"]
        assert "interface GigabitEthernet0/0.10" in _cli(sim, "r1", "show running-config")[0]
        assert _cli(sim, "r1", "show interfaces g0/0")[0].startswith("GigabitEthernet0/0 is up")

    def test_switch_port_header_shows_status_word(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "show interfaces fa0/1", "show interfaces fa0/5")
        assert out[1].startswith("FastEthernet0/1 is up, line protocol is up (connected)")
        assert out[2].startswith("FastEthernet0/5 is down, line protocol is down (notconnect)")

    def test_short_names_where_ios_uses_them(self) -> None:
        sim = access_lab()
        status = _cli(sim, "sw1", "enable", "show interfaces status")[1]
        assert status.splitlines()[1].startswith("Fa0/0 ") or status.splitlines()[1].startswith("Fa0/1 ")
        assert "FastEthernet" not in status

    def test_mac_addresses_in_cisco_notation(self) -> None:
        sim = access_lab()
        configure_access_router(sim)
        _ping(sim, "pc1", "192.168.1.1")
        for cmd, dev in (("show interfaces fa0/1", "sw1"), ("show mac address-table", "sw1"),
                         ("show spanning-tree", "sw1"), ("show arp", "r1")):
            out = _cli(sim, dev, "enable", cmd)[1]
            assert DOTTED_MAC.search(out), f"{cmd}: {out}"
            assert not re.search(r"[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}", out), f"{cmd}: {out}"


# ---------------------------------------------------------------------------
# 3. Switch tables
# ---------------------------------------------------------------------------

class TestSwitchTables:
    def test_show_vlan_brief_lists_access_ports_only(self) -> None:
        sim = roas_lab()
        out = _cli(sim, "sw1", "show vlan brief")[0]
        vlan1 = next(l for l in out.splitlines() if l.startswith("1 "))
        assert "Fa0/23" not in out          # the trunk
        assert vlan1.split()[3] == "Fa0/0,"  # wrapped list starts with first access port
        assert re.search(r"^10\s+VLAN0010\s+active\s+Fa0/1$", out, re.M)
        assert "1002 fddi-default                     act/unsup" in out

    def test_show_vlan_includes_type_table(self) -> None:
        sim = roas_lab()
        out = _cli(sim, "sw1", "show vlan")[0]
        assert "VLAN Type  SAID       MTU" in out
        assert re.search(r"^10\s+enet\s+100010\s+1500", out, re.M)

    def test_show_interfaces_switchport(self) -> None:
        sim = roas_lab()
        access = _cli(sim, "sw1", "show interfaces fa0/1 switchport")[0]
        assert "Administrative Mode: static access" in access
        assert "Access Mode VLAN: 10 (VLAN0010)" in access
        trunk = _cli(sim, "sw1", "show interfaces fa0/23 switchport")[0]
        assert "Administrative Mode: trunk" in trunk
        assert "Operational Mode: trunk" in trunk
        assert "Trunking VLANs Enabled: ALL" in trunk
        everything = _cli(sim, "sw1", "show interfaces switchport")[0]
        assert everything.count("Name: ") == 24

    def test_show_interfaces_status_columns(self) -> None:
        sim = roas_lab()
        out = _cli(sim, "sw1", "show interfaces status")[0]
        fa01 = next(l for l in out.splitlines() if l.startswith("Fa0/1 "))
        fa05 = next(l for l in out.splitlines() if l.startswith("Fa0/5 "))
        assert fa01.split()[1:] == ["connected", "10", "a-full", "a-100", "10/100BaseTX"]
        assert fa05.split()[1:] == ["notconnect", "1", "auto", "auto", "10/100BaseTX"]

    def test_mac_table_filters_and_clear(self) -> None:
        sim = roas_lab()
        _ping(sim, "pc10", "192.168.20.10")
        full = _cli(sim, "sw1", "show mac address-table")[0]
        assert full.endswith("Total Mac Addresses for this criterion: 4")
        vlan10 = _cli(sim, "sw1", "show mac address-table vlan 10")[0]
        assert all(l.split()[0] == "10" for l in vlan10.splitlines()[5:-1])
        port = _cli(sim, "sw1", "show mac address-table interface fa0/2")[0]
        assert port.endswith("criterion: 1")
        _cli(sim, "sw1", "clear mac address-table dynamic")
        assert _cli(sim, "sw1", "show mac address-table")[0].endswith("criterion: 0")


# ---------------------------------------------------------------------------
# 4. Spanning-tree wording
# ---------------------------------------------------------------------------

class TestSpanningTreeWording:
    def test_rapid_pvst_says_rstp(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "show spanning-tree", "show spanning-tree summary")
        assert "Spanning tree enabled protocol rstp" in out[1]
        assert "Switch is in rapid-pvst mode" in out[2]

    def test_switch_model_with_pvst_default(self) -> None:
        from tests.test_e2e_labs import _switch
        sw = _switch("sw1")
        sw.stp_mode = "pvst"
        sim = _build([_pc("pc1", "10.0.0.1/24"), sw], [("pc1", "eth0", "sw1", "Fa0/1")])
        out = _cli(sim, "sw1", "enable", "show spanning-tree")[1]
        assert "Spanning tree enabled protocol ieee" in out


# ---------------------------------------------------------------------------
# 5. Errors, help, pipes
# ---------------------------------------------------------------------------

class TestErrorsAndHelp:
    def test_caret_under_offending_token(self) -> None:
        sim = access_lab()
        s = _session(sim, "sw1")
        prompt = s.prompt()
        out = s.execute("shwo version")
        caret, header = out.split("\n")
        assert header == "% Invalid input detected at '^' marker."
        assert caret.index("^") == len(prompt)
        s.execute("enable")
        out = s.execute("show ip interface briefx")
        assert out.split("\n")[0].index("^") == len("SW1#") + len("show ip interface ")

    def test_caret_after_do_counts_the_do(self) -> None:
        sim = access_lab()
        s = _session(sim, "sw1")
        s.execute("enable")
        s.execute("conf t")
        out = s.execute("do show xyz")
        assert out.split("\n")[0].index("^") == len("SW1(config)#") + len("do show ")

    def test_word_help(self) -> None:
        sim = access_lab()
        s = _session(sim, "sw1")
        s.execute("enable")
        assert s.execute("show i?") == "ip  interfaces"
        assert "interface" in s.execute("show ip ?")   # argument help still works
        assert s.execute("zz?") == "% Unrecognized command"

    def test_pipes_are_case_sensitive_regexes(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "enable", "show running-config | include ^hostname|^interface Vlan",
                   "show running-config | include HOSTNAME")
        assert out[1].splitlines() == ["hostname SW1", "interface Vlan1"] or \
            set(out[1].splitlines()) <= {"hostname SW1", "interface Vlan1"}
        assert out[2] == ""


# ---------------------------------------------------------------------------
# 6. Small EXEC commands
# ---------------------------------------------------------------------------

class TestExecCommands:
    def test_bare_configure_prompts_for_source(self) -> None:
        sim = access_lab()
        s = _session(sim, "sw1")
        s.execute("enable")
        assert s.execute("configure") == ""
        assert s.prompt() == "Configuring from terminal, memory, or network [terminal]? "
        assert s.execute("").startswith("Enter configuration commands")
        assert s.mode == CLIMode.GLOBAL_CONFIG

    def test_terminal_length_and_history(self) -> None:
        sim = access_lab()
        out = _cli(sim, "sw1", "terminal length 0", "enable", "show history")
        assert out[0] == ""
        assert out[2].splitlines() == ["  terminal length 0", "  enable", "  show history"]

    def test_ping_unrecognized_host(self) -> None:
        sim = access_lab()
        assert _cli(sim, "pc1", "ping 999.1.1.1")[0] == \
            "% Unrecognized host or address, or protocol not running."
