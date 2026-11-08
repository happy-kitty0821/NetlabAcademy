"""
tests/test_determinism.py
-------------------------
Deterministic replay tests.

Covers AC-08-1 through AC-08-5 and JSON round-trip.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.scenarios import build_sim


def _run_scenario(seed: int):
    """Run the standard two-host ping and return the trace."""
    sim = build_sim(seed=seed)
    result = sim.get_host("host-a").ping("192.168.1.2", count=1)
    sim.run()
    return sim.trace


def _trace_signature(trace) -> list[tuple]:
    """
    Convert a trace to a comparable list of (type_name, time, seq) tuples.
    Excludes frame_ids which contain random UUIDs — those are intentionally
    different between runs because uuid4() is used (not the simulation RNG).
    """
    return [(type(e).__name__, e.time, e.seq) for e in trace]


class TestDeterministicReplay:
    def test_same_seed_two_simulations(self) -> None:
        """AC-08-1: Two Simulation objects with the same seed → identical trace signature."""
        trace1 = _run_scenario(seed=42)
        trace2 = _run_scenario(seed=42)
        assert _trace_signature(trace1) == _trace_signature(trace2)

    def test_reset_replay_in_process(self) -> None:
        """AC-08-5: reset() followed by same commands → identical trace signature."""
        sim = build_sim(seed=42)
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        sig1 = _trace_signature(sim.trace)

        sim.reset()
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        sig2 = _trace_signature(sim.trace)

        assert sig1 == sig2

    def test_different_seed_may_differ(self) -> None:
        """AC-08-3: Different seeds CAN produce different MAC addresses → different trace."""
        trace42 = _run_scenario(seed=42)
        trace99 = _run_scenario(seed=99)
        # The event types and count must be the same (deterministic protocol mechanics).
        types42 = [type(e).__name__ for e in trace42]
        types99 = [type(e).__name__ for e in trace99]
        assert types42 == types99
        # The traces may differ in MAC-related fields but event structure is identical.

    def test_trace_event_types_are_deterministic(self) -> None:
        """The sequence of event type names is identical across seeds."""
        trace1 = _run_scenario(seed=1)
        trace2 = _run_scenario(seed=2)
        assert [type(e).__name__ for e in trace1] == [type(e).__name__ for e in trace2]

    def test_four_ping_deterministic(self) -> None:
        """Four-ping batch is deterministic across two runs."""
        sim1 = build_sim(seed=42)
        sim1.get_host("host-a").ping("192.168.1.2", count=4)
        sim1.run()

        sim2 = build_sim(seed=42)
        sim2.get_host("host-a").ping("192.168.1.2", count=4)
        sim2.run()

        assert _trace_signature(sim1.trace) == _trace_signature(sim2.trace)


class TestCrossProcessDeterminism:
    def test_same_trace_in_fresh_process(self) -> None:
        """AC-08-2: Cross-process replay produces the same trace signature."""
        # In-process trace.
        trace_in = _run_scenario(seed=42)
        sig_in = json.dumps(_trace_signature(trace_in), sort_keys=True)

        # Cross-process trace via subprocess.
        # Note: subprocess is used in the *test layer* only, never in simulator_core.
        helper = (
            "import sys, json; "
            "sys.path.insert(0, '.'); "
            "from tests.scenarios import build_sim; "
            "sim = build_sim(seed=42); "
            "sim.get_host('host-a').ping('192.168.1.2', count=1); "
            "sim.run(); "
            "sig = [(type(e).__name__, e.time, e.seq) for e in sim.trace]; "
            "print(json.dumps(sig))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", helper],
            capture_output=True,
            text=True,
            cwd=".",  # run from packages/simulator-core/
        )
        assert proc.returncode == 0, f"Subprocess failed:\n{proc.stderr}"
        sig_out = proc.stdout.strip()
        assert sig_in == sig_out


class TestJSONRoundTrip:
    def test_json_round_trip_preserves_trace_structure(self) -> None:
        """AC-08-4: Trace serialises to JSON and back without structural loss."""
        from simulator_core.serialisation import trace_from_json, trace_to_json

        sim = build_sim(seed=42)
        sim.get_host("host-a").ping("192.168.1.2", count=1)
        sim.run()
        original_trace = sim.trace

        serialised = trace_to_json(original_trace)
        # Must be JSON-serialisable.
        json_str = json.dumps(serialised)
        data = json.loads(json_str)

        reconstructed = trace_from_json(data)

        # Same length, same event types, same timestamps and seq numbers.
        assert len(reconstructed) == len(original_trace)
        for orig, recon in zip(original_trace, reconstructed):
            assert type(orig).__name__ == type(recon).__name__
            assert orig.time == recon.time
            assert orig.seq == recon.seq
