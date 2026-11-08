"""
tests/test_failures.py
----------------------
Negative-case tests for failure scenarios.

Covers AC-07-1 through AC-07-6.
"""

from __future__ import annotations

import random

import pytest

from simulator_core.events import (
    ARPRequestSent,
    FrameDropped,
    FrameTransmit,
    DROP_INTERFACE_ADMIN_DOWN,
    DROP_LINK_DOWN,
    DROP_NO_ROUTE,
    DROP_PORT_DOWN,
)
from simulator_core.exceptions import ConfigurationError
from simulator_core.simulation import Simulation
from simulator_core.types import InterfaceState
from tests.scenarios import (
    build_two_host_topology,
    configure_same_subnet,
    build_sim,
)


class TestInterfaceDown:
    def test_interface_down_produces_frame_dropped(self) -> None:
        """AC-07-1: Interface administratively DOWN → FrameDropped in trace."""
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

    def test_interface_down_drop_has_required_fields(self) -> None:
        """AC-07-5: Drop events include timestamp, device_id, reason and frame metadata."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        topo.devices[ha].interfaces["eth0"].admin_state = InterfaceState.DOWN
        sim = Simulation(topo, seed=1)
        sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()
        drops = [e for e in sim.trace if isinstance(e, FrameDropped)
                 and e.reason == DROP_INTERFACE_ADMIN_DOWN]
        assert len(drops) >= 1
        drop = drops[0]
        assert drop.time >= 0
        assert drop.device_id != ""
        assert drop.reason == DROP_INTERFACE_ADMIN_DOWN
        assert drop.frame is not None

    def test_interface_down_no_unhandled_exception(self) -> None:
        """AC-07-6: sim.run() must not raise when interface is down."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        topo.devices[ha].interfaces["eth0"].admin_state = InterfaceState.DOWN
        sim = Simulation(topo, seed=1)
        sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()  # must not raise


class TestNoIPConfigured:
    def test_no_ip_raises_configuration_error(self) -> None:
        """AC-07-2: ConfigurationError raised immediately when source has no IP."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        # Only configure host-b.
        topo.devices[hb].interfaces["eth0"].set_ip("192.168.1.2/24")
        sim = Simulation(topo, seed=1)
        with pytest.raises(ConfigurationError, match="no IP address configured"):
            sim.get_host(ha).ping("192.168.1.2")


class TestNoRoute:
    def test_different_subnets_no_gateway_returns_failed_result(self) -> None:
        """AC-07-3: No route → PingResult with success=False, no events in trace."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        topo.devices[ha].interfaces["eth0"].set_ip("192.168.1.1/24")
        topo.devices[hb].interfaces["eth0"].set_ip("10.0.0.2/24")
        sim = Simulation(topo, seed=1)
        result = sim.get_host(ha).ping("10.0.0.2", count=1)
        sim.run()
        # Pre-flight failure: returned immediately, no events scheduled.
        assert result.received == 0
        assert len(result.results) == 1
        assert result.results[0].success is False
        assert result.results[0].drop_reason == DROP_NO_ROUTE

    def test_no_route_trace_is_empty(self) -> None:
        """AC-07-3: No Ethernet frames, ARP requests or FrameDropped events generated."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        topo.devices[ha].interfaces["eth0"].set_ip("192.168.1.1/24")
        topo.devices[hb].interfaces["eth0"].set_ip("10.0.0.2/24")
        sim = Simulation(topo, seed=1)
        sim.get_host(ha).ping("10.0.0.2", count=1)
        sim.run()
        # No transmission events, no ARP, no drops.
        assert sim.trace == []

    def test_no_route_does_not_raise(self) -> None:
        """AC-07-3: ping() must return a result, not raise an exception."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        topo.devices[ha].interfaces["eth0"].set_ip("192.168.1.1/24")
        topo.devices[hb].interfaces["eth0"].set_ip("10.0.0.2/24")
        sim = Simulation(topo, seed=1)
        result = sim.get_host(ha).ping("10.0.0.2", count=1)  # must not raise
        assert result is not None


class TestDisconnectedLink:
    def test_link_down_after_arp_drops_icmp(self) -> None:
        """AC-07-4: Disconnecting the link after ARP resolution drops the ICMP echo."""
        # Phase 1: run ARP to populate caches.
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        sim = Simulation(topo, seed=1)
        # Populate ARP caches without sending ICMP (ping count=0 workaround:
        # run one full ping, then reset and bring the link down).
        sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()
        # host-a now has host-b in its ARP cache.
        from ipaddress import IPv4Address
        assert IPv4Address("192.168.1.2") in sim.get_host(ha).arp_cache

        # Phase 2: bring down the switch port to host-b and ping again.
        sim.topology.devices[sw].interfaces["Gi0/1"].admin_state = InterfaceState.DOWN
        result2 = sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()
        # The ICMP frames can no longer reach host-b — we expect drops.
        drops = [e for e in sim.trace if isinstance(e, FrameDropped)]
        assert len(drops) >= 1

    def test_link_down_no_unhandled_exception(self) -> None:
        """AC-07-6: sim.run() must not raise when a link goes down mid-session."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        topo.links[0].admin_state = InterfaceState.DOWN
        sim = Simulation(topo, seed=1)
        sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()  # must not raise

    def test_drop_event_has_required_fields(self) -> None:
        """AC-07-5: Drop events include timestamp, device_id, reason and frame."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        topo.devices[sw].interfaces["Gi0/1"].admin_state = InterfaceState.DOWN
        sim = Simulation(topo, seed=1)
        sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()
        drops = [e for e in sim.trace if isinstance(e, FrameDropped)]
        assert len(drops) >= 1
        for drop in drops:
            assert isinstance(drop.time, int)
            assert isinstance(drop.device_id, str) and drop.device_id
            assert isinstance(drop.reason, str) and drop.reason
            assert drop.frame is not None
