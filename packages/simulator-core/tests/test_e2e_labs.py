"""
tests/test_e2e_labs.py
----------------------
End-to-end lab scenarios driven through the CLI, the way a student builds
a lab: devices start unconfigured (except end-host addressing) and every
router/switch setting is typed at the IOS-style prompt.

These cover behaviour the unit suites missed because they tested pieces
in isolation:

  1. A host reaches another subnet through its default gateway (the host
     ARPs for the gateway, never for the off-link destination).
  2. Router addresses configured from the CLI create connected routes;
     shutdown withdraws them; static routes install only while their next
     hop is reachable.
  3. VLANs stay separate across 802.1Q trunks (tagging on egress,
     classification on ingress, allowed-VLAN filtering).
  4. Interface names are matched by type *and* exact number; ranges apply
     to every member; global commands work from sub-modes.
  5. Routers can ping (with IOS's ".!!!!" while ARP resolves) and show
     their ARP table.
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLIMode, CLISession
from simulator_core.events import ARPReplySent, ARPRequestSent, FrameDropped, FrameTransmit
from simulator_core.serialisation import trace_to_json
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel


# ---------------------------------------------------------------------------
# Topology builders (mirror the web catalog: 2960 = Fa0/0-23, 2911 = Gi0/0-2)
# ---------------------------------------------------------------------------

_seed = iter(range(1000, 100000))


def _mac() -> MACAddress:
    return MACAddress.generate(random.Random(next(_seed)))


def _pc(dev_id: str, ip: str, gateway: str | None = None) -> Device:
    d = Device(id=dev_id, model=DeviceModel.HOST, hostname=dev_id.upper())
    d.add_interface(Interface(name="eth0", mac=_mac()))
    d.interfaces["eth0"].set_ip(ip)
    if gateway:
        d.interfaces["eth0"].set_gateway(gateway)
    return d


def _switch(dev_id: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.SWITCH, hostname=dev_id.upper())
    for i in range(24):
        d.add_interface(Interface(name=f"Fa0/{i}", mac=_mac()))
    return d


def _router(dev_id: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.ROUTER, hostname=dev_id.upper())
    d.supports_svi = True
    d.supports_l3_routing = True
    for i in range(3):
        d.add_interface(Interface(name=f"Gi0/{i}", mac=_mac()))
    return d


def _build(devices: list[Device], links: list[tuple[str, str, str, str]]) -> Simulation:
    topo = Topology()
    for d in devices:
        topo.add_device(d)
    for n, (a, ia, b, ib) in enumerate(links):
        topo.add_link(Link(id=f"l{n}", endpoint_a=(a, ia), endpoint_b=(b, ib)))
    topo.validate()
    return Simulation(topo, seed=7)


def _cli(sim: Simulation, dev_id: str, *cmds: str) -> list[str]:
    s = _session(sim, dev_id)
    return [s.execute(c) for c in cmds]


_sessions: dict[tuple[int, str], CLISession] = {}


def _session(sim: Simulation, dev_id: str) -> CLISession:
    key = (id(sim), dev_id)
    if key not in _sessions:
        _sessions[key] = CLISession(device_id=dev_id, simulation=sim)
    return _sessions[key]


def _ping(sim: Simulation, dev_id: str, target: str) -> str:
    """Run ping from dev_id and return the '!'/'.' line."""
    out = _session(sim, dev_id).execute(f"ping {target}")
    lines = out.strip().splitlines()
    return next(l for l in lines if l and set(l) <= {"!", "."})


def routed_lab() -> Simulation:
    """PC-A ─ Gi0/0 R1 Gi0/1 ─ PC-B, router completely unconfigured."""
    return _build(
        [_pc("pca", "10.1.1.10/24", "10.1.1.1"),
         _pc("pcb", "10.2.2.10/24", "10.2.2.1"),
         _router("r1")],
        [("pca", "eth0", "r1", "Gi0/0"), ("pcb", "eth0", "r1", "Gi0/1")],
    )


def configure_r1(sim: Simulation) -> None:
    _cli(sim, "r1",
         "enable", "configure terminal",
         "interface g0/0", "ip address 10.1.1.1 255.255.255.0", "no shutdown",
         "interface g0/1", "ip address 10.2.2.1 255.255.255.0", "no shutdown",
         "end")


def two_router_lab() -> Simulation:
    """PC-A ─ R1 ─(10.0.12.0/30)─ R2 ─ PC-B with static routes."""
    sim = _build(
        [_pc("pca", "10.1.1.10/24", "10.1.1.1"),
         _pc("pcb", "10.3.3.10/24", "10.3.3.1"),
         _router("r1"), _router("r2")],
        [("pca", "eth0", "r1", "Gi0/0"),
         ("r1", "Gi0/1", "r2", "Gi0/1"),
         ("r2", "Gi0/0", "pcb", "eth0")],
    )
    _cli(sim, "r1", "enable", "conf t",
         "int g0/0", "ip address 10.1.1.1 255.255.255.0",
         "int g0/1", "ip address 10.0.12.1 255.255.255.252",
         "ip route 10.3.3.0 255.255.255.0 10.0.12.2", "end")
    _cli(sim, "r2", "enable", "conf t",
         "int g0/0", "ip address 10.3.3.1 255.255.255.0",
         "int g0/1", "ip address 10.0.12.2 255.255.255.252",
         "ip route 10.1.1.0 255.255.255.0 10.0.12.1", "end")
    return sim


def vlan_lab(pc3_vlan: int = 10) -> Simulation:
    """
    PC1 (VLAN 10) ─ SW1 ═trunk═ SW2 ─ PC3 (VLAN pc3_vlan)
    PC2 (VLAN 1)  ─ SW1
    """
    sim = _build(
        [_pc("pc1", "192.168.10.11/24"), _pc("pc2", "192.168.10.12/24"),
         _pc("pc3", "192.168.10.13/24"), _switch("sw1"), _switch("sw2")],
        [("pc1", "eth0", "sw1", "Fa0/1"), ("pc2", "eth0", "sw1", "Fa0/2"),
         ("sw1", "Fa0/23", "sw2", "Fa0/23"), ("pc3", "eth0", "sw2", "Fa0/1")],
    )
    _cli(sim, "sw1", "enable", "conf t", "vlan 10", "exit",
         "int fa0/1", "switchport mode access", "switchport access vlan 10",
         "int fa0/23", "switchport mode trunk", "end")
    pc3_cmds = ["enable", "conf t", "vlan 10", "exit",
                "int fa0/23", "switchport mode trunk"]
    if pc3_vlan != 1:
        pc3_cmds += ["int fa0/1", "switchport access vlan %d" % pc3_vlan]
    _cli(sim, "sw2", *pc3_cmds, "end")
    return sim


# ---------------------------------------------------------------------------
# 1 + 2. Routing through a CLI-configured router
# ---------------------------------------------------------------------------

class TestRoutedLab:
    def test_ping_fails_before_router_is_configured(self) -> None:
        sim = routed_lab()
        assert _ping(sim, "pca", "10.2.2.10") == "....."

    def test_ping_across_router_configured_from_cli(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        assert _ping(sim, "pca", "10.2.2.10") == "!!!!!"
        assert _ping(sim, "pcb", "10.1.1.10") == "!!!!!"

    def test_cli_addresses_create_connected_routes(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        out = _cli(sim, "r1", "show ip route")[0]
        assert "C    10.1.1.0/24 is directly connected, Gi0/0" in out
        assert "C    10.2.2.0/24 is directly connected, Gi0/1" in out

    def test_host_arps_for_gateway_not_remote_destination(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        _ping(sim, "pca", "10.2.2.10")
        targets = {str(e.message.target_ip) for e in sim.trace
                   if isinstance(e, ARPRequestSent) and e.device_id == "pca"}
        assert targets == {"10.1.1.1"}

    def test_shutdown_withdraws_connected_route_and_breaks_ping(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        _cli(sim, "r1", "conf t", "int g0/1", "shutdown", "end")
        assert "10.2.2.0" not in _cli(sim, "r1", "show ip route")[0]
        assert _ping(sim, "pca", "10.2.2.10") == "....."
        _cli(sim, "r1", "conf t", "int g0/1", "no shutdown", "end")
        assert "10.2.2.0/24 is directly connected" in _cli(sim, "r1", "show ip route")[0]
        assert _ping(sim, "pca", "10.2.2.10") == "!!!!!"

    def test_readdressing_replaces_connected_route(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        _cli(sim, "r1", "conf t", "int g0/1", "ip address 10.9.9.1 255.255.255.0", "end")
        out = _cli(sim, "r1", "show ip route")[0]
        assert "10.9.9.0/24" in out and "10.2.2.0" not in out

    def test_router_ignores_unicast_not_addressed_to_it(self) -> None:
        """A flooded unicast for another station must not be routed again."""
        sim = routed_lab()
        configure_r1(sim)
        _ping(sim, "pca", "10.2.2.10")
        # Exactly 5 echo requests leave R1 towards PC-B (no duplicates).
        echoes_out = [
            e for e in sim.trace
            if isinstance(e, FrameTransmit) and e.device_id == "r1"
            and e.interface_name == "Gi0/1"
            and e.frame.ethertype == 0x0800
        ]
        assert len(echoes_out) == 5


class TestStaticRoutes:
    def test_ping_across_two_routers_with_static_routes(self) -> None:
        sim = two_router_lab()
        assert _ping(sim, "pca", "10.3.3.10") == "!!!!!"

    def test_static_route_waits_for_reachable_next_hop(self) -> None:
        sim = routed_lab()
        _cli(sim, "r1", "enable", "conf t",
             "ip route 172.16.0.0 255.255.0.0 10.2.2.254")
        # Next hop not on any connected network yet: configured, not installed.
        assert "172.16.0.0" not in _cli(sim, "r1", "do show ip route")[0]
        _cli(sim, "r1", "int g0/1", "ip address 10.2.2.1 255.255.255.0")
        out = _cli(sim, "r1", "do show ip route")[0]
        assert "S    172.16.0.0/16 [1/0] via 10.2.2.254" in out

    def test_static_route_withdrawn_when_next_hop_interface_shuts(self) -> None:
        sim = two_router_lab()
        _cli(sim, "r1", "conf t", "int g0/1", "shutdown", "end")
        assert "10.3.3.0" not in _cli(sim, "r1", "show ip route")[0]

    def test_default_route_sets_gateway_of_last_resort(self) -> None:
        sim = two_router_lab()
        _cli(sim, "r1", "conf t", "ip route 0.0.0.0 0.0.0.0 10.0.12.2", "end")
        out = _cli(sim, "r1", "show ip route")[0]
        assert "Gateway of last resort is 10.0.12.2 to network 0.0.0.0" in out
        assert "S*   0.0.0.0/0 [1/0] via 10.0.12.2" in out


# ---------------------------------------------------------------------------
# 3. VLANs across 802.1Q trunks
# ---------------------------------------------------------------------------

class TestVlanTrunking:
    def test_same_vlan_hosts_communicate_across_trunk(self) -> None:
        sim = vlan_lab(pc3_vlan=10)
        assert _ping(sim, "pc1", "192.168.10.13") == "!!!!!"

    def test_different_vlans_are_isolated_across_trunk(self) -> None:
        sim = vlan_lab(pc3_vlan=1)
        assert _ping(sim, "pc1", "192.168.10.13") == "....."
        # The VLAN 10 ARP broadcast must never reach the VLAN 1 host.
        assert not [e for e in sim.trace
                    if isinstance(e, ARPReplySent) and e.device_id == "pc3"]

    def test_vlan_isolation_on_one_switch(self) -> None:
        sim = vlan_lab(pc3_vlan=10)
        assert _ping(sim, "pc1", "192.168.10.12") == "....."  # PC2 is VLAN 1

    def test_trunk_tags_non_native_vlans_only(self) -> None:
        sim = vlan_lab(pc3_vlan=10)
        _ping(sim, "pc1", "192.168.10.13")
        on_trunk = [e.frame.vlan_tag for e in sim.trace
                    if isinstance(e, FrameTransmit) and e.interface_name == "Fa0/23"
                    and e.frame.bpdu_payload is None and e.frame.cdp_payload is None]
        assert on_trunk and set(on_trunk) == {10}
        # Access ports deliver untagged frames to hosts.
        to_hosts = [e.frame.vlan_tag for e in sim.trace
                    if isinstance(e, FrameTransmit) and e.device_id in ("sw1", "sw2")
                    and e.interface_name == "Fa0/1"]
        assert to_hosts and set(to_hosts) == {None}

    def test_native_vlan_crosses_trunk_untagged(self) -> None:
        sim = vlan_lab(pc3_vlan=10)
        _ping(sim, "pc2", "192.168.10.13")  # PC2 is VLAN 1 = native; PC3 is not
        on_trunk = {e.frame.vlan_tag for e in sim.trace
                    if isinstance(e, FrameTransmit) and e.interface_name == "Fa0/23"
                    and e.frame.bpdu_payload is None and e.frame.cdp_payload is None}
        assert on_trunk == {None}

    def test_vlan_pruned_from_trunk_is_dropped(self) -> None:
        sim = vlan_lab(pc3_vlan=10)
        _cli(sim, "sw2", "conf t", "int fa0/23", "switchport trunk allowed vlan 20", "end")
        assert _ping(sim, "pc1", "192.168.10.13") == "....."
        reasons = {e.reason for e in sim.trace if isinstance(e, FrameDropped)}
        assert "VLAN 10 not allowed on trunk" in reasons


# ---------------------------------------------------------------------------
# 4. Interface naming, ranges and sub-mode fall-through
# ---------------------------------------------------------------------------

class TestInterfaceNames:
    @pytest.mark.parametrize("name", [
        "fa0/1", "f0/1", "FastEthernet0/1", "fastethernet0/1",
        "FastEthernet 0/1", "fa 0/1",
    ])
    def test_valid_switch_names_select_fa0_1(self, name: str) -> None:
        sim = vlan_lab()
        s = _session(sim, "sw1")
        s.execute("conf t")
        assert s.execute(f"interface {name}") == ""
        assert s.current_iface == "Fa0/1"

    @pytest.mark.parametrize("name", [
        "fa0/1.10",   # subinterface: must not fall back to Fa0/10
        "g0/1",       # wrong type: switch has FastEthernet only
        "GigabitEthernet0/1",
        "e0/1",
        "0/1",        # no type
        "fa0/24",     # out of range
    ])
    def test_invalid_switch_names_are_rejected(self, name: str) -> None:
        sim = vlan_lab()
        s = _session(sim, "sw1")
        s.execute("conf t")
        out = s.execute(f"interface {name}")
        assert out.startswith("%")
        assert s.mode == CLIMode.GLOBAL_CONFIG
        assert s.current_iface is None

    def test_router_rejects_fastethernet_name(self) -> None:
        sim = routed_lab()
        s = _session(sim, "r1")
        s.execute("enable")
        s.execute("conf t")
        assert s.execute("interface fa0/0").startswith("%")
        assert s.execute("interface GigabitEthernet 0/2") == ""
        assert s.current_iface == "Gi0/2"

    def test_interface_range_applies_to_every_member(self) -> None:
        sim = vlan_lab()
        _cli(sim, "sw1", "conf t", "vlan 20", "exit",
             "interface range fa0/3 - 5 , f0/8", "switchport access vlan 20", "end")
        ports = sim.topology.devices["sw1"].interfaces
        assert [ports[f"Fa0/{i}"].vlan for i in (3, 4, 5, 6, 7, 8)] == [20, 20, 20, 1, 1, 20]

    def test_interface_command_from_interface_mode_switches_interface(self) -> None:
        sim = routed_lab()
        _cli(sim, "r1", "enable", "conf t",
             "interface g0/0", "ip address 10.1.1.1 255.255.255.0",
             "interface g0/1", "ip address 10.2.2.1 255.255.255.0", "end")
        ifaces = sim.topology.devices["r1"].interfaces
        assert str(ifaces["Gi0/0"].ip_config) == "10.1.1.1/24"
        assert str(ifaces["Gi0/1"].ip_config) == "10.2.2.1/24"

    def test_global_command_from_interface_mode(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        s = _session(sim, "r1")
        s.execute("conf t")
        s.execute("interface g0/1")
        assert s.execute("ip route 172.16.0.0 255.255.0.0 10.2.2.254") == ""
        assert s.mode == CLIMode.GLOBAL_CONFIG
        assert "172.16.0.0/16" in s.execute("do show ip route")

    def test_invalid_command_in_interface_mode_stays_in_mode(self) -> None:
        sim = routed_lab()
        s = _session(sim, "r1")
        s.execute("enable")
        s.execute("conf t")
        s.execute("interface g0/1")
        assert s.execute("bogus command").startswith("% Invalid input")
        assert s.mode == CLIMode.IFACE_CONFIG and s.current_iface == "Gi0/1"

    def test_show_interfaces_accepts_abbreviations_on_router(self) -> None:
        sim = routed_lab()
        out = _cli(sim, "r1", "enable", "show interfaces g0/1",
                   "show interfaces fa0/9")
        assert out[1].startswith("Gi0/1 is")
        assert out[2].startswith("% Invalid input")


# ---------------------------------------------------------------------------
# 5. Router-originated ping and router ARP table
# ---------------------------------------------------------------------------

class TestRouterPing:
    def test_first_ping_drops_one_echo_while_arp_resolves(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        assert _ping(sim, "r1", "10.2.2.10") == ".!!!!"
        assert _ping(sim, "r1", "10.2.2.10") == "!!!!!"

    def test_router_pings_remote_network_via_static_route(self) -> None:
        sim = two_router_lab()
        _ping(sim, "r1", "10.3.3.10")
        assert _ping(sim, "r1", "10.3.3.10") == "!!!!!"

    def test_router_ping_without_route(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        out = _cli(sim, "r1", "ping 8.8.8.8")[0]
        assert "....." in out
        assert "no route to destination" in out

    def test_router_pings_its_own_address(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        assert _ping(sim, "r1", "10.1.1.1") == "!!!!!"

    def test_unanswered_arp_reports_reason_and_does_not_leak(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        out = _cli(sim, "r1", "ping 10.2.2.99")[0]
        assert "....." in out and "no ARP reply" in out
        # A later successful ping is unaffected by the stale attempt.
        _ping(sim, "r1", "10.2.2.10")
        out = _cli(sim, "r1", "ping 10.2.2.10")[0]
        assert "!!!!!" in out
        assert "round-trip min/avg/max = -" not in out

    def test_show_arp_on_router(self) -> None:
        sim = routed_lab()
        configure_r1(sim)
        _ping(sim, "pca", "10.2.2.10")
        out = _cli(sim, "r1", "show arp")[0]
        assert "not supported" not in out
        assert "10.1.1.1         -" in out          # own interface
        assert "10.1.1.10" in out and "Gi0/0" in out  # learned neighbour
        assert "10.2.2.10" in out and "Gi0/1" in out

    def test_switch_ping_explains_limitation(self) -> None:
        sim = vlan_lab()
        out = _cli(sim, "sw1", "ping 192.168.10.11")[0]
        assert "Layer 2 switch" in out


# ---------------------------------------------------------------------------
# Determinism: the same lab replays identically
# ---------------------------------------------------------------------------

def _strip_ids(obj):
    if isinstance(obj, dict):
        return {k: _strip_ids(v) for k, v in obj.items() if k != "frame_id"}
    if isinstance(obj, list):
        return [_strip_ids(v) for v in obj]
    return obj


def test_routed_vlan_lab_is_deterministic() -> None:
    def run() -> list:
        global _seed
        _seed = iter(range(1000, 100000))
        sim = two_router_lab()
        _ping(sim, "pca", "10.3.3.10")
        sim2 = vlan_lab()
        _ping(sim2, "pc1", "192.168.10.13")
        return _strip_ids(trace_to_json(sim.trace) + trace_to_json(sim2.trace))

    assert run() == run()
