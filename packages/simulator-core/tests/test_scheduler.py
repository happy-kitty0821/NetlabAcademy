"""
tests/test_scheduler.py
-----------------------
Unit tests for EventScheduler and basic Simulation lifecycle (skeleton).

Covers: event ordering, depth limit, is_empty/peek_time, clear(),
Simulation init/run/reset with an empty queue.
"""

from __future__ import annotations

import pytest

from simulator_core.events import (
    ARPCacheUpdated,
    FrameArrival,
    SimulationEvent,
    TraceLimitReached,
)
from simulator_core.exceptions import SimulationLimitError
from simulator_core.scheduler import EventScheduler


# ---------------------------------------------------------------------------
# EventScheduler — ordering
# ---------------------------------------------------------------------------


def _make_arp_cache_event(time: int, seq: int) -> ARPCacheUpdated:
    return ARPCacheUpdated(
        time=time, seq=seq, device_id="d1",
        ip_address="1.2.3.4", mac_address="aa:bb:cc:dd:ee:ff",
    )


class TestEventSchedulerOrdering:
    def test_single_event(self) -> None:
        sched = EventScheduler()
        evt = _make_arp_cache_event(time=5, seq=0)
        sched.schedule(evt)
        assert sched.pop() is evt

    def test_two_events_different_times(self) -> None:
        sched = EventScheduler()
        late = _make_arp_cache_event(time=10, seq=0)
        early = _make_arp_cache_event(time=2, seq=1)
        sched.schedule(late)
        sched.schedule(early)
        assert sched.pop() is early
        assert sched.pop() is late

    def test_same_time_ordered_by_seq(self) -> None:
        sched = EventScheduler()
        # seq 0 should come out first.
        e0 = _make_arp_cache_event(time=5, seq=0)
        e1 = _make_arp_cache_event(time=5, seq=1)
        e2 = _make_arp_cache_event(time=5, seq=2)
        sched.schedule(e2)
        sched.schedule(e0)
        sched.schedule(e1)
        assert sched.pop() is e0
        assert sched.pop() is e1
        assert sched.pop() is e2

    def test_mixed_times_and_seqs(self) -> None:
        sched = EventScheduler()
        events = [
            _make_arp_cache_event(time=3, seq=2),
            _make_arp_cache_event(time=1, seq=0),
            _make_arp_cache_event(time=3, seq=0),
            _make_arp_cache_event(time=2, seq=1),
        ]
        for e in events:
            sched.schedule(e)
        popped = [sched.pop() for _ in range(4)]
        # Should be sorted by (time, seq):
        # (1,0), (2,1), (3,0), (3,2)
        assert [(e.time, e.seq) for e in popped] == [(1, 0), (2, 1), (3, 0), (3, 2)]


class TestEventSchedulerEmptyAndPeek:
    def test_is_empty_on_new_scheduler(self) -> None:
        sched = EventScheduler()
        assert sched.is_empty()

    def test_is_empty_false_after_schedule(self) -> None:
        sched = EventScheduler()
        sched.schedule(_make_arp_cache_event(time=1, seq=0))
        assert not sched.is_empty()

    def test_is_empty_true_after_all_popped(self) -> None:
        sched = EventScheduler()
        sched.schedule(_make_arp_cache_event(time=1, seq=0))
        sched.pop()
        assert sched.is_empty()

    def test_peek_time_none_when_empty(self) -> None:
        sched = EventScheduler()
        assert sched.peek_time() is None

    def test_peek_time_returns_smallest(self) -> None:
        sched = EventScheduler()
        sched.schedule(_make_arp_cache_event(time=10, seq=0))
        sched.schedule(_make_arp_cache_event(time=3, seq=1))
        assert sched.peek_time() == 3

    def test_len(self) -> None:
        sched = EventScheduler()
        assert len(sched) == 0
        sched.schedule(_make_arp_cache_event(time=1, seq=0))
        assert len(sched) == 1


class TestEventSchedulerDepthLimit:
    def test_exceeding_limit_raises(self) -> None:
        sched = EventScheduler(max_depth=3)
        for i in range(3):
            sched.schedule(_make_arp_cache_event(time=i, seq=i))
        with pytest.raises(SimulationLimitError, match="depth limit"):
            sched.schedule(_make_arp_cache_event(time=3, seq=3))

    def test_existing_events_intact_after_limit_error(self) -> None:
        sched = EventScheduler(max_depth=2)
        e0 = _make_arp_cache_event(time=0, seq=0)
        e1 = _make_arp_cache_event(time=1, seq=1)
        sched.schedule(e0)
        sched.schedule(e1)
        with pytest.raises(SimulationLimitError):
            sched.schedule(_make_arp_cache_event(time=2, seq=2))
        # Queue still has original two events.
        assert len(sched) == 2


class TestEventSchedulerClear:
    def test_clear_empties_queue(self) -> None:
        sched = EventScheduler()
        for i in range(5):
            sched.schedule(_make_arp_cache_event(time=i, seq=i))
        sched.clear()
        assert sched.is_empty()

    def test_clear_resets_seq_counter(self) -> None:
        sched = EventScheduler()
        for _ in range(3):
            sched.next_seq()
        sched.clear()
        assert sched.next_seq() == 0


class TestEventSchedulerNextSeq:
    def test_seq_monotonically_increasing(self) -> None:
        sched = EventScheduler()
        seqs = [sched.next_seq() for _ in range(5)]
        assert seqs == list(range(5))


# ---------------------------------------------------------------------------
# Simulation skeleton lifecycle (no protocol logic yet)
# ---------------------------------------------------------------------------


def _build_minimal_topology() -> object:
    """Build the standard two-host-one-switch topology for lifecycle tests."""
    import random
    from simulator_core.addresses import MACAddress
    from simulator_core.topology import Device, Interface, Link, Topology
    from simulator_core.types import DeviceModel

    def _mac(seed: int) -> MACAddress:
        return MACAddress.generate(random.Random(seed))

    topo = Topology()
    ha = Device(id="host-a", model=DeviceModel.HOST, hostname="PC-A")
    ha.add_interface(Interface(name="eth0", mac=_mac(1)))
    hb = Device(id="host-b", model=DeviceModel.HOST, hostname="PC-B")
    hb.add_interface(Interface(name="eth0", mac=_mac(2)))
    sw = Device(id="switch-1", model=DeviceModel.SWITCH, hostname="SW1")
    sw.add_interface(Interface(name="Gi0/0", mac=_mac(3)))
    sw.add_interface(Interface(name="Gi0/1", mac=_mac(4)))
    topo.add_device(ha)
    topo.add_device(hb)
    topo.add_device(sw)
    topo.add_link(Link(id="l1", endpoint_a=("host-a", "eth0"), endpoint_b=("switch-1", "Gi0/0")))
    topo.add_link(Link(id="l2", endpoint_a=("host-b", "eth0"), endpoint_b=("switch-1", "Gi0/1")))
    return topo


class TestSimulationLifecycle:
    def test_init_clock_is_zero(self) -> None:
        from simulator_core.simulation import Simulation
        sim = Simulation(_build_minimal_topology(), seed=0)
        assert sim.clock == 0

    def test_init_trace_is_empty(self) -> None:
        from simulator_core.simulation import Simulation
        sim = Simulation(_build_minimal_topology(), seed=0)
        assert sim.trace == []

    def test_run_empty_queue_completes(self) -> None:
        from simulator_core.simulation import Simulation
        sim = Simulation(_build_minimal_topology(), seed=0)
        sim.run()  # must return without error

    def test_step_empty_returns_none(self) -> None:
        from simulator_core.simulation import Simulation
        sim = Simulation(_build_minimal_topology(), seed=0)
        result = sim.step()
        assert result is None

    def test_reset_restores_clock(self) -> None:
        from simulator_core.simulation import Simulation
        from simulator_core.events import ARPCacheUpdated
        sim = Simulation(_build_minimal_topology(), seed=0)
        # Manually put an event in the queue and advance the clock.
        seq = sim.next_seq()
        evt = ARPCacheUpdated(time=5, seq=seq, device_id="host-a",
                              ip_address="1.2.3.4", mac_address="aa:bb:cc:dd:ee:ff")
        sim.schedule(evt)
        sim.run()
        assert sim.clock == 5
        sim.reset()
        assert sim.clock == 0

    def test_reset_clears_trace(self) -> None:
        from simulator_core.simulation import Simulation
        from simulator_core.events import ARPCacheUpdated
        sim = Simulation(_build_minimal_topology(), seed=0)
        seq = sim.next_seq()
        evt = ARPCacheUpdated(time=1, seq=seq, device_id="host-a",
                              ip_address="1.2.3.4", mac_address="aa:bb:cc:dd:ee:ff")
        sim.schedule(evt)
        sim.run()
        assert len(sim.trace) == 1
        sim.reset()
        assert sim.trace == []

    def test_tick_limit_raises(self) -> None:
        from simulator_core.simulation import Simulation
        from simulator_core.events import ARPCacheUpdated
        sim = Simulation(_build_minimal_topology(), seed=0, max_ticks=10)
        seq = sim.next_seq()
        evt = ARPCacheUpdated(time=11, seq=seq, device_id="host-a",
                              ip_address="1.2.3.4", mac_address="aa:bb:cc:dd:ee:ff")
        with pytest.raises(SimulationLimitError, match="max_ticks"):
            sim.schedule(evt)
