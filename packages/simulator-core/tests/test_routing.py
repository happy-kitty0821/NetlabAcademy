"""
tests/test_routing.py
---------------------
Tests for the routing table, router device, and routed topology scenarios.

Topology used in integration tests:

  PC-A (192.168.1.1/24)  ──  SW1  ──  R1 Gi0/0 (192.168.1.254/24)
                                       R1 Gi0/1 (10.0.0.1/24)
                              SW2  ──  R1 Gi0/1
  PC-B (10.0.0.2/24)     ──  SW2
"""

from __future__ import annotations

import random
from ipaddress import IPv4Address, IPv4Network

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.devices.router import Router
from simulator_core.events import FrameDropped, DROP_NO_ROUTE, DROP_TTL_EXCEEDED
from simulator_core.routing import RouteEntry, RouteSource, RoutingTable
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel


def _mac(seed: int) -> MACAddress:
    return MACAddress.generate(random.Random(seed))


# ── RoutingTable unit tests ───────────────────────────────────────────────────


class TestRoutingTable:
    def test_empty_lookup_returns_none(self) -> None:
        rt = RoutingTable()
        assert rt.lookup(IPv4Address("10.0.0.1")) is None

    def test_connected_route_lookup(self) -> None:
        rt = RoutingTable()
        rt.add_connected_route(IPv4Network("192.168.1.0/24"), "eth0")
        entry = rt.lookup(IPv4Address("192.168.1.5"))
        assert entry is not None
        assert entry.source == RouteSource.CONNECTED
        assert entry.outgoing_interface == "eth0"

    def test_no_match_outside_subnet(self) -> None:
        rt = RoutingTable()
        rt.add_connected_route(IPv4Network("192.168.1.0/24"), "eth0")
        assert rt.lookup(IPv4Address("10.0.0.1")) is None

    def test_static_route_lookup(self) -> None:
        rt = RoutingTable()
        rt.add_static_route(
            IPv4Network("10.0.0.0/8"),
            IPv4Address("192.168.1.254"),
            "eth0",
        )
        entry = rt.lookup(IPv4Address("10.0.0.1"))
        assert entry is not None
        assert entry.source == RouteSource.STATIC
        assert str(entry.next_hop) == "192.168.1.254"

    def test_longest_prefix_wins(self) -> None:
        rt = RoutingTable()
        rt.add_static_route(IPv4Network("10.0.0.0/8"), IPv4Address("1.1.1.1"), "eth0")
        rt.add_static_route(IPv4Network("10.0.0.0/24"), IPv4Address("2.2.2.2"), "eth1")
        entry = rt.lookup(IPv4Address("10.0.0.5"))
        assert entry is not None
        assert str(entry.next_hop) == "2.2.2.2"  # /24 beats /8

    def test_default_route(self) -> None:
        rt = RoutingTable()
        rt.add_static_route(IPv4Network("0.0.0.0/0"), IPv4Address("192.168.1.1"), "eth0")
        entry = rt.lookup(IPv4Address("8.8.8.8"))
        assert entry is not None
        assert entry.network == IPv4Network("0.0.0.0/0")

    def test_remove_static_route(self) -> None:
        rt = RoutingTable()
        net = IPv4Network("10.0.0.0/8")
        rt.add_static_route(net, IPv4Address("1.1.1.1"), "eth0")
        assert rt.remove_static_route(net) is True
        assert rt.lookup(IPv4Address("10.0.0.1")) is None

    def test_connected_overrides_on_readd(self) -> None:
        rt = RoutingTable()
        rt.add_connected_route(IPv4Network("192.168.1.0/24"), "eth0")
        rt.add_connected_route(IPv4Network("192.168.1.0/24"), "eth1")  # update
        # Should have only one entry, on eth1
        matches = [r for r in rt.routes if r.network == IPv4Network("192.168.1.0/24")]
        assert len(matches) == 1
        assert matches[0].outgoing_interface == "eth1"

    def test_routes_sorted_longest_first(self) -> None:
        rt = RoutingTable()
        rt.add_static_route(IPv4Network("0.0.0.0/0"), IPv4Address("1.1.1.1"), "eth0")
        rt.add_static_route(IPv4Network("10.0.0.0/8"), IPv4Address("2.2.2.2"), "eth1")
        rt.add_connected_route(IPv4Network("10.0.0.0/24"), "eth2")
        prefixes = [r.prefix_length for r in rt.routes]
        assert prefixes == sorted(prefixes, reverse=True)


# ── Routed topology helpers ───────────────────────────────────────────────────

def build_routed_topology() -> tuple[Topology, dict]:
    """
    PC-A ── SW1 ── R1(Gi0/0) ── R1(Gi0/1) ── SW2 ── PC-B
    Networks:
      Left : 192.168.1.0/24 — PC-A: .1, R1 Gi0/0: .254
      Right: 10.0.0.0/24   — PC-B: .2, R1 Gi0/1: .1
    """
    topo = Topology()
    ids: dict = {}

    # Devices
    pc_a = Device(id="pc-a", model=DeviceModel.HOST, hostname="PC-A")
    pc_a.add_interface(Interface(name="eth0", mac=_mac(1)))
    pc_a.interfaces["eth0"].set_ip("192.168.1.1/24")
    pc_a.interfaces["eth0"].set_gateway("192.168.1.254")

    pc_b = Device(id="pc-b", model=DeviceModel.HOST, hostname="PC-B")
    pc_b.add_interface(Interface(name="eth0", mac=_mac(2)))
    pc_b.interfaces["eth0"].set_ip("10.0.0.2/24")
    pc_b.interfaces["eth0"].set_gateway("10.0.0.1")

    sw1 = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
    sw1.add_interface(Interface(name="Gi0/0", mac=_mac(3)))
    sw1.add_interface(Interface(name="Gi0/1", mac=_mac(4)))

    sw2 = Device(id="sw2", model=DeviceModel.SWITCH, hostname="SW2")
    sw2.add_interface(Interface(name="Gi0/0", mac=_mac(5)))
    sw2.add_interface(Interface(name="Gi0/1", mac=_mac(6)))

    r1 = Device(id="r1", model=DeviceModel.ROUTER, hostname="R1")
    r1.add_interface(Interface(name="Gi0/0", mac=_mac(7)))
    r1.add_interface(Interface(name="Gi0/1", mac=_mac(8)))
    r1.interfaces["Gi0/0"].set_ip("192.168.1.254/24")
    r1.interfaces["Gi0/1"].set_ip("10.0.0.1/24")

    for dev in [pc_a, pc_b, sw1, sw2, r1]:
        topo.add_device(dev)
        ids[dev.id] = dev.id

    # Links
    topo.add_link(Link(id="l1", endpoint_a=("pc-a", "eth0"),   endpoint_b=("sw1", "Gi0/0")))
    topo.add_link(Link(id="l2", endpoint_a=("sw1", "Gi0/1"),   endpoint_b=("r1",  "Gi0/0")))
    topo.add_link(Link(id="l3", endpoint_a=("r1",  "Gi0/1"),   endpoint_b=("sw2", "Gi0/0")))
    topo.add_link(Link(id="l4", endpoint_a=("sw2", "Gi0/1"),   endpoint_b=("pc-b", "eth0")))

    return topo, ids


class TestRouterConnectedRoutes:
    def test_connected_routes_built_on_init(self) -> None:
        topo, _ = build_routed_topology()
        sim = Simulation(topo, seed=1)
        router = sim.get_router("r1")
        rt = router.routing_table

        entry_left = rt.lookup(IPv4Address("192.168.1.1"))
        assert entry_left is not None
        assert entry_left.outgoing_interface == "Gi0/0"

        entry_right = rt.lookup(IPv4Address("10.0.0.2"))
        assert entry_right is not None
        assert entry_right.outgoing_interface == "Gi0/1"

    def test_no_route_to_other_network_on_host(self) -> None:
        """Host's routing table is empty; it uses default gateway."""
        topo, _ = build_routed_topology()
        sim = Simulation(topo, seed=1)
        host = sim.get_host("pc-a")
        # Host itself has no routing — it needs the router
        # But its gateway is set so ping to 10.0.0.2 should NOT immediately
        # return DROP_NO_ROUTE in this topology (gateway is reachable).
        # We just verify the host gateway is configured:
        iface = topo.devices["pc-a"].interfaces["eth0"]
        assert iface.default_gateway == "192.168.1.254"


class TestStaticRoutes:
    def test_add_and_lookup_static_route(self) -> None:
        topo, _ = build_routed_topology()
        sim = Simulation(topo, seed=1)
        router = sim.get_router("r1")
        from ipaddress import IPv4Address, IPv4Network
        router.routing_table.add_static_route(
            IPv4Network("172.16.0.0/16"),
            IPv4Address("192.168.1.100"),
            "Gi0/0",
        )
        entry = router.routing_table.lookup(IPv4Address("172.16.1.5"))
        assert entry is not None
        assert str(entry.next_hop) == "192.168.1.100"


class TestTTLDecrement:
    def test_ttl_expired_produces_frame_dropped(self) -> None:
        """A packet with TTL=1 arriving at the router should be dropped."""
        topo, _ = build_routed_topology()
        sim = Simulation(topo, seed=1)

        # Manually craft a TTL=1 packet arriving at R1 Gi0/0
        from simulator_core.addresses import MACAddress
        from simulator_core.frames import EthernetFrame, ICMPMessage, IPv4Packet
        from simulator_core.events import FrameArrival

        pc_a_mac = topo.devices["pc-a"].interfaces["eth0"].mac
        r1_mac   = topo.devices["r1"].interfaces["Gi0/0"].mac

        icmp = ICMPMessage(type=8, code=0, sequence=0, identifier=0)
        pkt = IPv4Packet(
            src=IPv4Address("192.168.1.1"),
            dst=IPv4Address("10.0.0.2"),
            protocol=1,
            ttl=1,  # will hit 0 after decrement
            payload=icmp,
        )
        frame = EthernetFrame(
            src_mac=pc_a_mac,
            dst_mac=r1_mac,
            ethertype=EthernetFrame.ETHERTYPE_IPV4,
            payload=pkt,
            frame_id="test-frame-ttl",
        )
        arrival = FrameArrival(
            time=1, seq=0,
            device_id="r1",
            interface_name="Gi0/0",
            frame=frame,
        )
        # Process the event directly
        router = sim.get_router("r1")
        router.handle_frame_arrival(arrival)
        sim.run()

        drops = [e for e in sim.trace if isinstance(e, FrameDropped)
                 and e.reason == DROP_TTL_EXCEEDED]
        assert len(drops) >= 1


class TestRoutingCLI:
    def test_show_ip_route_on_router(self) -> None:
        from simulator_core.cli import CLISession
        topo, _ = build_routed_topology()
        sim = Simulation(topo, seed=1)
        s = CLISession(device_id="r1", simulation=sim)
        s.execute("enable")
        out = s.execute("show ip route")
        assert "C" in out or "192.168.1.0" in out
        assert "10.0.0.0" in out

    def test_ip_route_command(self) -> None:
        from simulator_core.cli import CLISession
        topo, _ = build_routed_topology()
        sim = Simulation(topo, seed=1)
        s = CLISession(device_id="r1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        out = s.execute("ip route 172.16.0.0 255.255.0.0 192.168.1.100")
        assert out == "" or "%" not in out
        s.execute("end")
        route_out = s.execute("show ip route")
        assert "172.16.0.0" in route_out

    def test_no_ip_route_removes_route(self) -> None:
        from simulator_core.cli import CLISession
        topo, _ = build_routed_topology()
        sim = Simulation(topo, seed=1)
        s = CLISession(device_id="r1", simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        s.execute("ip route 172.16.0.0 255.255.0.0 192.168.1.100")
        s.execute("no ip route 172.16.0.0 255.255.0.0 192.168.1.100")
        s.execute("end")
        route_out = s.execute("show ip route")
        assert "172.16.0.0" not in route_out
