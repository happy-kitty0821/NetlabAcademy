"""
tests/test_icmp_timing.py
--------------------------
Regression tests for ICMP echo request/reply timing.

Verifies that multiple echo requests within a single ping session are
scheduled at different logical ticks (not all at the same tick), and
that replies are therefore also interleaved with their corresponding
requests in the trace rather than batched up.
"""

from __future__ import annotations

from simulator_core.events import ICMPEchoRequestSent, ICMPEchoReplySent, FrameTransmit
from tests.scenarios import build_sim


class TestICMPTiming:
    def test_echo_requests_at_distinct_ticks(self) -> None:
        """Each echo request in a 4-ping batch must be at a different logical tick."""
        sim = build_sim(seed=42)
        sim.get_host("host-a").ping("192.168.1.2", count=4)
        sim.run()

        req_times = [
            e.time for e in sim.trace
            if isinstance(e, ICMPEchoRequestSent)
        ]
        assert len(req_times) == 4, f"Expected 4 requests, got {len(req_times)}"
        # All ticks must be distinct.
        assert len(set(req_times)) == 4, (
            f"Echo requests must be at distinct ticks; got {req_times}"
        )
        # Ticks must be monotonically increasing.
        assert req_times == sorted(req_times), (
            f"Request ticks must be in order; got {req_times}"
        )

    def test_echo_replies_at_distinct_ticks(self) -> None:
        """Each echo reply must be at a different logical tick."""
        sim = build_sim(seed=42)
        sim.get_host("host-a").ping("192.168.1.2", count=4)
        sim.run()

        rep_times = [
            e.time for e in sim.trace
            if isinstance(e, ICMPEchoReplySent)
        ]
        assert len(rep_times) == 4
        assert len(set(rep_times)) == 4, (
            f"Echo replies must be at distinct ticks; got {rep_times}"
        )

    def test_request_reply_interleaved_not_batched(self) -> None:
        """
        The trace must NOT have all requests before all replies.
        For each seq N, the reply must come after the request in the trace.
        """
        sim = build_sim(seed=42)
        sim.get_host("host-a").ping("192.168.1.2", count=4)
        sim.run()

        # Build a map: seq → (request_trace_index, reply_trace_index)
        req_idx: dict[int, int] = {}
        rep_idx: dict[int, int] = {}
        for i, evt in enumerate(sim.trace):
            if isinstance(evt, ICMPEchoRequestSent):
                req_idx[evt.message.sequence] = i
            elif isinstance(evt, ICMPEchoReplySent):
                rep_idx[evt.message.sequence] = i

        for seq in range(4):
            assert seq in req_idx, f"Missing request for seq {seq}"
            assert seq in rep_idx, f"Missing reply for seq {seq}"
            assert req_idx[seq] < rep_idx[seq], (
                f"Reply for seq {seq} appears before its request in the trace"
            )

    def test_no_batch_of_frameTransmits(self) -> None:
        """
        There should be no run of more than 2 consecutive FrameTransmit events.
        With RTT_SPACING=6, each ping is fully resolved before the next starts.
        """
        sim = build_sim(seed=42)
        sim.get_host("host-a").ping("192.168.1.2", count=4)
        sim.run()

        max_run = 0
        current_run = 0
        for evt in sim.trace:
            if isinstance(evt, FrameTransmit):
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0

        assert max_run <= 2, (
            f"Found a run of {max_run} consecutive FrameTransmits — "
            f"requests are still being batched (timing bug)"
        )

    def test_single_ping_correct_event_sequence(self) -> None:
        """
        For count=1, verify the trace follows the expected order:
        ARP resolution → ICMP request → ICMP reply (no batching possible).
        """
        sim = build_sim(seed=42)
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()

        from simulator_core.events import ARPRequestSent, ARPReplySent

        types = [type(e).__name__ for e in sim.trace]
        # ARP request must appear before ICMP request.
        assert "ARPRequestSent" in types
        assert "ICMPEchoRequestSent" in types
        assert "ICMPEchoReplySent" in types
        assert types.index("ARPRequestSent") < types.index("ICMPEchoRequestSent"), \
            "ARP must precede ICMP request"
        assert types.index("ICMPEchoRequestSent") < types.index("ICMPEchoReplySent"), \
            "ICMP request must precede ICMP reply"
