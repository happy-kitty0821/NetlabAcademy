"""
tests/test_icmp.py
------------------
Integration tests for ICMP echo (ping).

Covers AC-05-1 through AC-05-6.
"""

from __future__ import annotations

from simulator_core.events import (
    ARPRequestSent,
    ICMPEchoReplySent,
    ICMPEchoRequestSent,
)
from tests.scenarios import build_sim


class TestICMPEcho:
    def test_ping_succeeds(self) -> None:
        """AC-05-1 to AC-05-3: Successful ping produces received=1."""
        sim = build_sim()
        result = sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        assert result.received == 1
        assert len(result.results) == 1
        assert result.results[0].success is True
        assert result.results[0].rtt_ticks is not None
        assert result.results[0].rtt_ticks > 0

    def test_icmp_request_event_in_trace(self) -> None:
        """AC-05-4: ICMPEchoRequestSent appears in trace."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        requests = [e for e in sim.trace if isinstance(e, ICMPEchoRequestSent)]
        assert len(requests) == 1

    def test_icmp_reply_event_in_trace(self) -> None:
        """AC-05-4: ICMPEchoReplySent appears in trace."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        replies = [e for e in sim.trace if isinstance(e, ICMPEchoReplySent)]
        assert len(replies) == 1

    def test_request_before_reply_in_trace(self) -> None:
        """ICMPEchoRequestSent must appear before ICMPEchoReplySent in the trace."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        req_time = next(e.time for e in sim.trace if isinstance(e, ICMPEchoRequestSent))
        rep_time = next(e.time for e in sim.trace if isinstance(e, ICMPEchoReplySent))
        assert req_time < rep_time

    def test_four_echo_batch(self) -> None:
        """AC-05-6: A four-echo ping produces received=4."""
        sim = build_sim()
        result = sim.get_host("host-a").ping("192.168.1.2", count=4)
        sim.run()
        assert result.received == 4
        assert len(result.results) == 4
        assert all(r.success for r in result.results)

    def test_second_ping_no_new_arp(self) -> None:
        """AC-05-5: Second ping uses cached ARP entry — no second ARPRequestSent."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        arp_count_after_first = sum(
            1 for e in sim.trace if isinstance(e, ARPRequestSent)
        )

        result2 = sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        arp_count_after_second = sum(
            1 for e in sim.trace if isinstance(e, ARPRequestSent)
        )

        assert arp_count_after_first == 1
        assert arp_count_after_second == 1  # no new ARP request
        assert result2.received == 1

    def test_sequence_numbers_unique(self) -> None:
        """Each echo request in a batch has a unique sequence number."""
        sim = build_sim()
        sim.get_host("host-a").ping("192.168.1.2", count=4)
        sim.run()
        req_events = [e for e in sim.trace if isinstance(e, ICMPEchoRequestSent)]
        seqs = [e.message.sequence for e in req_events]
        assert len(seqs) == len(set(seqs))

    def test_rtt_is_positive(self) -> None:
        """Round-trip time recorded is a positive integer."""
        sim = build_sim()
        result = sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        assert result.results[0].rtt_ticks is not None
        assert result.results[0].rtt_ticks > 0
