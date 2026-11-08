"""
tests/test_host.py
------------------
Unit tests for Host protocol logic.

Covers: IP config acceptance/rejection, ARP cache state, pre-flight checks,
and interface-down behaviour.
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.events import ARPCacheUpdated, FrameDropped, DROP_INTERFACE_ADMIN_DOWN, DROP_NO_ROUTE
from simulator_core.exceptions import ConfigurationError
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel, InterfaceState
from simulator_core.simulation import Simulation
from tests.scenarios import build_sim, build_two_host_topology, configure_same_subnet


def _mac(seed: int) -> MACAddress:
    return MACAddress.generate(random.Random(seed))


# =============================================================================
# IP configuration
# =============================================================================


class TestHostIPConfig:
    def test_valid_cidr_accepted(self) -> None:
        sim = build_sim()
        host = sim.get_host("host-a")
        iface = host._device.interfaces["eth0"]
        # Already configured by build_sim — verify it is set.
        assert iface.ip_config is not None
        assert str(iface.ip_config.address) == "192.168.1.1"

    def test_malformed_cidr_raises(self) -> None:
        sim = build_sim()
        host = sim.get_host("host-a")
        with pytest.raises(ConfigurationError):
            host._device.interfaces["eth0"].set_ip("999.0.0.1/24")

    def test_network_address_raises(self) -> None:
        sim = build_sim()
        host = sim.get_host("host-a")
        with pytest.raises(ConfigurationError):
            host._device.interfaces["eth0"].set_ip("192.168.1.0/24")

    def test_broadcast_address_raises(self) -> None:
        sim = build_sim()
        host = sim.get_host("host-a")
        with pytest.raises(ConfigurationError):
            host._device.interfaces["eth0"].set_ip("192.168.1.255/24")


# =============================================================================
# ARP cache
# =============================================================================


class TestHostARPCache:
    def test_arp_cache_starts_empty(self) -> None:
        sim = build_sim()
        host = sim.get_host("host-a")
        assert host.arp_cache == {}

    def test_arp_cache_populated_after_exchange(self) -> None:
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        cache = sim.get_host("host-a").arp_cache
        from ipaddress import IPv4Address
        assert IPv4Address("192.168.1.2") in cache

    def test_arp_cache_updated_event_in_trace(self) -> None:
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        updates = [e for e in sim.trace if isinstance(e, ARPCacheUpdated)
                   and e.device_id == "host-a"]
        assert len(updates) >= 1


# =============================================================================
# Pre-flight checks
# =============================================================================


class TestHostPreFlightChecks:
    def test_no_ip_raises_configuration_error(self) -> None:
        """Host with no IP configured raises ConfigurationError immediately."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        # Only configure host-b; leave host-a without IP.
        configure_same_subnet(topo, hb, "192.168.1.2/24", ha, "192.168.1.1/24")
        # Reset host-a's IP.
        topo.devices[ha].interfaces["eth0"].ip_config = None
        sim = Simulation(topo, seed=1)
        with pytest.raises(ConfigurationError, match="no IP address configured"):
            sim.get_host(ha).ping("192.168.1.2")

    def test_no_route_returns_failed_result_not_exception(self) -> None:
        """Ping to different subnet with no gateway returns PingResult, not exception."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        # Host-a on 192.168.1.x, host-b on 10.0.0.x — different subnets.
        topo.devices[ha].interfaces["eth0"].set_ip("192.168.1.1/24")
        topo.devices[hb].interfaces["eth0"].set_ip("10.0.0.1/24")
        sim = Simulation(topo, seed=1)
        result = sim.get_host(ha).ping("10.0.0.1", count=1)
        assert result.received == 0
        assert len(result.results) == 1
        assert result.results[0].success is False
        assert result.results[0].drop_reason == DROP_NO_ROUTE

    def test_no_route_no_events_scheduled(self) -> None:
        """No Ethernet frames or ARP events are generated for a no-route ping."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        topo.devices[ha].interfaces["eth0"].set_ip("192.168.1.1/24")
        topo.devices[hb].interfaces["eth0"].set_ip("10.0.0.1/24")
        sim = Simulation(topo, seed=1)
        sim.get_host(ha).ping("10.0.0.1", count=4)
        sim.run()
        # Trace must be empty — no events were scheduled.
        assert sim.trace == []

    def test_no_route_count_respected(self) -> None:
        """All count echo results are marked failed with the correct reason."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        topo.devices[ha].interfaces["eth0"].set_ip("192.168.1.1/24")
        topo.devices[hb].interfaces["eth0"].set_ip("10.0.0.1/24")
        sim = Simulation(topo, seed=1)
        result = sim.get_host(ha).ping("10.0.0.1", count=4)
        assert result.count == 4
        assert result.sent == 4
        assert result.received == 0
        assert all(r.drop_reason == DROP_NO_ROUTE for r in result.results)


# =============================================================================
# Interface down behaviour
# =============================================================================


class TestHostInterfaceDown:
    def test_interface_down_drops_frame(self) -> None:
        """A frame sent on an administratively DOWN interface produces a FrameDropped."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        topo.devices[ha].interfaces["eth0"].admin_state = InterfaceState.DOWN
        sim = Simulation(topo, seed=1)
        sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()
        drops = [e for e in sim.trace if isinstance(e, FrameDropped)]
        assert len(drops) >= 1
        assert any(d.reason == DROP_INTERFACE_ADMIN_DOWN for d in drops)

    def test_interface_down_no_unhandled_exception(self) -> None:
        """sim.run() must not propagate an unhandled exception on interface-down."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        topo.devices[ha].interfaces["eth0"].admin_state = InterfaceState.DOWN
        sim = Simulation(topo, seed=1)
        sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()  # must not raise
