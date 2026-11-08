"""
tests/test_arp.py
-----------------
Integration tests for the full ARP request/reply cycle.

Covers AC-04-1 through AC-04-8.
"""

from __future__ import annotations

from ipaddress import IPv4Address

from simulator_core.events import (
    ARPCacheUpdated,
    ARPReplySent,
    ARPRequestSent,
    FrameTransmit,
)
from tests.scenarios import build_sim


class TestARPCycle:
    def test_arp_cache_starts_empty(self) -> None:
        """AC-04-1: Before any ARP exchange, both hosts' caches are empty."""
        sim = build_sim()
        assert sim.get_host("host-a").arp_cache == {}
        assert sim.get_host("host-b").arp_cache == {}

    def test_exactly_one_arp_request_broadcast(self) -> None:
        """AC-04-2: A single ARPRequest broadcast is scheduled on cache miss."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        requests = [e for e in sim.trace if isinstance(e, ARPRequestSent)]
        assert len(requests) == 1

    def test_exactly_one_arp_reply(self) -> None:
        """AC-04-4: Host-B sends exactly one ARP reply."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        replies = [e for e in sim.trace if isinstance(e, ARPReplySent)]
        assert len(replies) == 1

    def test_host_a_cache_populated_after_exchange(self) -> None:
        """AC-04-5: After the reply, host-a has host-b's MAC in its cache."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        cache_a = sim.get_host("host-a").arp_cache
        assert IPv4Address("192.168.1.2") in cache_a
        mac_b = sim.topology.devices["host-b"].interfaces["eth0"].mac
        assert cache_a[IPv4Address("192.168.1.2")] == mac_b

    def test_host_b_cache_populated_from_request(self) -> None:
        """AC-04-6: Host-B learns host-a's MAC from the incoming ARP request."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        cache_b = sim.get_host("host-b").arp_cache
        assert IPv4Address("192.168.1.1") in cache_b
        mac_a = sim.topology.devices["host-a"].interfaces["eth0"].mac
        assert cache_b[IPv4Address("192.168.1.1")] == mac_a

    def test_arp_events_in_trace(self) -> None:
        """AC-04-7: ARP events are recorded in the trace with metadata."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        request_evts = [e for e in sim.trace if isinstance(e, ARPRequestSent)]
        reply_evts = [e for e in sim.trace if isinstance(e, ARPReplySent)]
        cache_evts = [e for e in sim.trace if isinstance(e, ARPCacheUpdated)]
        assert len(request_evts) == 1
        assert len(reply_evts) == 1
        assert len(cache_evts) >= 2  # host-a and host-b each update their caches

    def test_no_second_arp_on_cache_hit(self) -> None:
        """AC-04-8: A second ping to the same target reuses the cached ARP entry."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        first_requests = [e for e in sim.trace if isinstance(e, ARPRequestSent)]
        assert len(first_requests) == 1

        # Second ping — should not trigger another ARP request.
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        all_requests = [e for e in sim.trace if isinstance(e, ARPRequestSent)]
        assert len(all_requests) == 1  # still only one from the first ping

    def test_arp_events_timestamp_ordering(self) -> None:
        """ARP events appear in non-decreasing time order."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        arp_events = [
            e for e in sim.trace
            if isinstance(e, (ARPRequestSent, ARPReplySent, ARPCacheUpdated))
        ]
        times = [e.time for e in arp_events]
        assert times == sorted(times)

    def test_arp_request_sent_before_reply(self) -> None:
        """ARP request must appear in the trace before the ARP reply."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        req_time = next(
            e.time for e in sim.trace if isinstance(e, ARPRequestSent)
        )
        rep_time = next(
            e.time for e in sim.trace if isinstance(e, ARPReplySent)
        )
        assert req_time < rep_time
