"""
tests/test_limits.py
--------------------
Resource-limit and host-isolation tests.

Covers AC-09-1 through AC-09-5.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from pathlib import Path

import pytest

from simulator_core.events import ARPCacheUpdated, TraceLimitReached
from simulator_core.exceptions import SimulationLimitError, TopologyError
from simulator_core.simulation import Simulation
from tests.scenarios import build_sim, build_two_host_topology, configure_same_subnet
import random


# =============================================================================
# AC-09-1: No forbidden imports in simulator_core production code
# =============================================================================

FORBIDDEN_IMPORT_NAMES = frozenset({"socket", "subprocess", "ctypes", "cffi"})
SIMULATOR_CORE_ROOT = Path(__file__).parent.parent / "simulator_core"


def _collect_simulator_py_files() -> list[Path]:
    return list(SIMULATOR_CORE_ROOT.rglob("*.py"))


def _get_imported_names(source: str) -> set[str]:
    """
    Parse *source* with the AST and return the set of top-level module names
    that are imported (handles ``import X``, ``import X as Y``,
    ``from X import ...``).
    """
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # "import socket" → "socket"; "import os.path" → "os"
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


class TestNoForbiddenImports:
    def test_simulator_core_does_not_import_forbidden_modules(self) -> None:
        """
        AC-09-1: Walk every .py file in simulator_core/ and assert none of them
        imports socket, subprocess, ctypes or cffi.
        """
        violations: list[str] = []
        for py_file in _collect_simulator_py_files():
            source = py_file.read_text(encoding="utf-8")
            imported = _get_imported_names(source)
            bad = imported & FORBIDDEN_IMPORT_NAMES
            if bad:
                violations.append(f"{py_file.relative_to(SIMULATOR_CORE_ROOT)}: {bad}")

        assert violations == [], (
            "simulator_core source files must not import host-I/O modules.\n"
            "Violations:\n" + "\n".join(violations)
        )


# =============================================================================
# AC-09-2: Queue overflow raises SimulationLimitError
# =============================================================================


class TestQueueOverflow:
    def test_queue_overflow_raises(self) -> None:
        """AC-09-2, AC-03-6: Scheduling beyond max_queue raises SimulationLimitError."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        # max_queue=1: ping() tries to schedule 2 events (ARPRequestSent + FrameTransmit).
        # The second schedule call overflows the queue.
        sim = Simulation(topo, seed=1, max_queue=1)
        with pytest.raises(SimulationLimitError):
            sim.get_host(ha).ping("192.168.1.2", count=1)


# =============================================================================
# AC-09-2 cont: Tick overflow raises SimulationLimitError
# =============================================================================


class TestTickOverflow:
    def test_tick_overflow_raises(self) -> None:
        """AC-03-7, AC-09-2: Event beyond max_ticks raises SimulationLimitError."""
        sim = build_sim(seed=1)
        seq = sim.next_seq()
        evt = ARPCacheUpdated(
            time=sim._max_ticks + 1, seq=seq,
            device_id="host-a", ip_address="1.2.3.4", mac_address="aa:bb:cc:dd:ee:ff",
        )
        with pytest.raises(SimulationLimitError, match="max_ticks"):
            sim.schedule(evt)


# =============================================================================
# AC-09-3: Node cap raises TopologyError
# =============================================================================


class TestNodeCap:
    def test_node_cap_exceeded_raises(self) -> None:
        """AC-09-3: Adding more nodes than max_nodes raises TopologyError."""
        from simulator_core.topology import Device, Interface, Topology
        from simulator_core.types import DeviceModel
        from simulator_core.addresses import MACAddress

        topo = Topology(max_nodes=2)
        d1 = Device(id="d1", model=DeviceModel.HOST, hostname="H1")
        d1.add_interface(Interface(name="eth0", mac=MACAddress.generate(random.Random(1))))
        d2 = Device(id="d2", model=DeviceModel.HOST, hostname="H2")
        d2.add_interface(Interface(name="eth0", mac=MACAddress.generate(random.Random(2))))
        d3 = Device(id="d3", model=DeviceModel.HOST, hostname="H3")
        d3.add_interface(Interface(name="eth0", mac=MACAddress.generate(random.Random(3))))
        topo.add_device(d1)
        topo.add_device(d2)
        with pytest.raises(TopologyError, match="node limit"):
            topo.add_device(d3)


# =============================================================================
# AC-09-4: Trace cap records TraceLimitReached sentinel
# =============================================================================


class TestTraceCap:
    def test_trace_cap_records_sentinel(self) -> None:
        """AC-09-4: When max_trace is hit, TraceLimitReached is appended."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        sim = Simulation(topo, seed=1, max_trace=5)
        sim.get_host(ha).ping("192.168.1.2", count=4)
        sim.run()
        sentinels = [e for e in sim.trace if isinstance(e, TraceLimitReached)]
        assert len(sentinels) >= 1

    def test_trace_does_not_grow_past_cap(self) -> None:
        """Trace length must not exceed max_trace + 1 (the sentinel itself)."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        cap = 5
        sim = Simulation(topo, seed=1, max_trace=cap)
        sim.get_host(ha).ping("192.168.1.2", count=4)
        sim.run()
        assert len(sim.trace) <= cap + 1

    def test_simulation_continues_after_trace_cap(self) -> None:
        """The simulation does not crash when the trace cap is reached."""
        rng = random.Random(1)
        topo, ha, hb, sw = build_two_host_topology(rng)
        configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
        sim = Simulation(topo, seed=1, max_trace=3)
        sim.get_host(ha).ping("192.168.1.2", count=1)
        sim.run()  # must complete without exception
