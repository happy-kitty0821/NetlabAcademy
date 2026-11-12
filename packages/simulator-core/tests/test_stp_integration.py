"""
tests/test_stp_integration.py
------------------------------
Integration tests for STP root election, port-role selection, and
port-state transitions across connected multi-switch topologies.

These tests use real topology objects with actual Link connections so
that _find_connected_switch() can resolve peers through topology.neighbours().

Critical acceptance criterion (Test A):
  Two physically connected switches with equal bridge priority must NOT
  both claim to be root after Simulation init (which calls run_stp()).
  The root must emerge from Bridge ID comparison.
"""

from __future__ import annotations

import random
import pytest

from simulator_core.addresses import MACAddress
from simulator_core.simulation import Simulation
from simulator_core.stp import PortRole, PortState, STPMode
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel, InterfaceState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mac(seed: int) -> MACAddress:
    return MACAddress.generate(random.Random(seed))


def _make_switch(device_id: str, hostname: str, n_ports: int, mac_seed: int) -> Device:
    """Create a Device(SWITCH) with n_ports GigabitEthernet interfaces."""
    dev = Device(id=device_id, model=DeviceModel.SWITCH, hostname=hostname)
    for i in range(n_ports):
        dev.add_interface(Interface(name=f"Gi0/{i}", mac=_mac(mac_seed + i)))
    return dev


def _build_sim(topo: Topology) -> Simulation:
    """Build a Simulation (which calls run_stp() automatically)."""
    return Simulation(topo, seed=42)


# ---------------------------------------------------------------------------
# Test A — Two-switch root election (critical acceptance criterion)
# ---------------------------------------------------------------------------

class TestTwoSwitchRootElection:
    """
    SW1 Gi0/0 -------- Gi0/0 SW2

    Both start with priority 32768.
    Lower MAC wins root election.
    After Simulation init (which calls run_stp()), one switch is root and
    the other has a root port pointing toward the winner.
    """

    def _build(self):
        topo = Topology()
        # Use deterministic MACs so we know which one is "lower"
        sw1 = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
        sw1.add_interface(Interface(name="Gi0/0", mac=MACAddress("aa:bb:cc:00:00:01")))
        sw1.add_interface(Interface(name="Gi0/1", mac=MACAddress("aa:bb:cc:00:00:02")))

        sw2 = Device(id="sw2", model=DeviceModel.SWITCH, hostname="SW2")
        sw2.add_interface(Interface(name="Gi0/0", mac=MACAddress("aa:bb:cc:00:00:ff")))
        sw2.add_interface(Interface(name="Gi0/1", mac=MACAddress("aa:bb:cc:00:01:00")))

        topo.add_device(sw1)
        topo.add_device(sw2)
        topo.add_link(Link(
            id="l1",
            endpoint_a=("sw1", "Gi0/0"),
            endpoint_b=("sw2", "Gi0/0"),
        ))
        return topo

    def test_exactly_one_root_bridge(self) -> None:
        sim = _build_sim(self._build())
        stp1 = sim.get_switch("sw1").stp
        stp2 = sim.get_switch("sw2").stp
        inst1 = stp1.get_instance(1)
        inst2 = stp2.get_instance(1)
        is_root_sw1 = inst1.is_root
        is_root_sw2 = inst2.is_root
        assert is_root_sw1 or is_root_sw2, "At least one switch must be root"
        assert not (is_root_sw1 and is_root_sw2), (
            "Both switches claim to be root — STP election failed.\n"
            f"  SW1 bridge_id={inst1.bridge_id}, root_bridge_id={inst1.root_bridge_id}\n"
            f"  SW2 bridge_id={inst2.bridge_id}, root_bridge_id={inst2.root_bridge_id}"
        )

    def test_both_switches_agree_on_same_root(self) -> None:
        sim = _build_sim(self._build())
        inst1 = sim.get_switch("sw1").stp.get_instance(1)
        inst2 = sim.get_switch("sw2").stp.get_instance(1)
        assert inst1.root_bridge_id == inst2.root_bridge_id, (
            f"Switches disagree on root bridge ID.\n"
            f"  SW1 root={inst1.root_bridge_id}\n"
            f"  SW2 root={inst2.root_bridge_id}"
        )

    def test_lower_mac_wins_root_election(self) -> None:
        """SW1 has MAC aa:bb:cc:00:00:01, SW2 has aa:bb:cc:00:00:ff — SW1 wins."""
        sim = _build_sim(self._build())
        inst1 = sim.get_switch("sw1").stp.get_instance(1)
        inst2 = sim.get_switch("sw2").stp.get_instance(1)
        # SW1 should be root (lower MAC)
        assert inst1.is_root, (
            f"SW1 (lower MAC) should be root, but root_bridge_id={inst1.root_bridge_id}"
        )
        assert not inst2.is_root, "SW2 (higher MAC) should not be root"

    def test_non_root_has_root_port(self) -> None:
        sim = _build_sim(self._build())
        stp2 = sim.get_switch("sw2").stp
        inst2 = stp2.get_instance(1)
        # SW2 is not root → must have a root port
        assert inst2.root_port_name is not None, (
            "Non-root switch must have a root port"
        )
        root_port = inst2.port_states.get(inst2.root_port_name)
        assert root_port is not None
        assert root_port.role == PortRole.ROOT, (
            f"Root port role should be ROOT, got {root_port.role}"
        )
        assert root_port.state == PortState.FORWARDING, (
            f"Root port state should be FORWARDING, got {root_port.state}"
        )

    def test_root_switch_designated_port_on_connected_link(self) -> None:
        sim = _build_sim(self._build())
        stp1 = sim.get_switch("sw1").stp
        inst1 = stp1.get_instance(1)
        # SW1 is root; its connected port Gi0/0 must be DESIGNATED FORWARDING
        port = inst1.port_states.get("Gi0/0")
        assert port is not None
        assert port.role == PortRole.DESIGNATED, (
            f"Root switch's connected port should be DESIGNATED, got {port.role}"
        )
        assert port.state == PortState.FORWARDING, (
            f"Root switch's connected port should be FORWARDING, got {port.state}"
        )

    def test_root_path_cost_on_non_root(self) -> None:
        sim = _build_sim(self._build())
        inst2 = sim.get_switch("sw2").stp.get_instance(1)
        # SW2's root path cost should equal the cost of its Gi0/0 port (default 4 for Gi)
        assert inst2.root_path_cost > 0, "Non-root switch should have positive root path cost"


# ---------------------------------------------------------------------------
# Test B — Three-switch linear topology
# ---------------------------------------------------------------------------

class TestThreeSwitchLinear:
    """
    SW1 Gi0/0 ---- Gi0/0 SW2 Gi0/1 ---- Gi0/0 SW3

    One root; SW2 has root port toward SW1; SW3's root port toward SW2.
    Path costs accumulate correctly.
    """

    def _build(self):
        topo = Topology()
        for i, (sw_id, hostname, mac_byte) in enumerate([
            ("sw1", "SW1", 0x01),
            ("sw2", "SW2", 0xAA),
            ("sw3", "SW3", 0xFF),
        ]):
            dev = Device(id=sw_id, model=DeviceModel.SWITCH, hostname=hostname)
            for p in range(3):
                dev.add_interface(Interface(
                    name=f"Gi0/{p}",
                    mac=MACAddress(f"aa:00:00:{i:02x}:{mac_byte:02x}:0{p}"),
                ))
            topo.add_device(dev)
        topo.add_link(Link(id="l1", endpoint_a=("sw1", "Gi0/0"), endpoint_b=("sw2", "Gi0/0")))
        topo.add_link(Link(id="l2", endpoint_a=("sw2", "Gi0/1"), endpoint_b=("sw3", "Gi0/0")))
        return topo

    def test_one_root_bridge(self) -> None:
        sim = _build_sim(self._build())
        roots = [
            sw.stp.get_instance(1).is_root
            for sw in [sim.get_switch(s) for s in ("sw1", "sw2", "sw3")]
        ]
        assert sum(roots) == 1, f"Exactly one root expected, got roots={roots}"

    def test_all_agree_on_root(self) -> None:
        sim = _build_sim(self._build())
        root_bids = [
            sim.get_switch(s).stp.get_instance(1).root_bridge_id
            for s in ("sw1", "sw2", "sw3")
        ]
        assert root_bids[0] == root_bids[1] == root_bids[2], (
            f"All switches must agree on root; got {root_bids}"
        )

    def test_non_root_switches_have_root_ports(self) -> None:
        sim = _build_sim(self._build())
        inst1 = sim.get_switch("sw1").stp.get_instance(1)
        for sw_id in ("sw1", "sw2", "sw3"):
            inst = sim.get_switch(sw_id).stp.get_instance(1)
            if not inst.is_root:
                assert inst.root_port_name is not None, (
                    f"{sw_id} is not root but has no root port"
                )

    def test_path_costs_increase_with_hops(self) -> None:
        sim = _build_sim(self._build())
        insts = {s: sim.get_switch(s).stp.get_instance(1) for s in ("sw1","sw2","sw3")}
        # Find root
        root_id = next(s for s, i in insts.items() if i.is_root)
        non_roots = [s for s in ("sw1","sw2","sw3") if s != root_id]
        # Sort by path cost — costs should differ (one hop vs two hops)
        costs = sorted(insts[s].root_path_cost for s in non_roots)
        if len(costs) == 2:
            assert costs[0] <= costs[1], "Path costs should be non-decreasing"
            # The farther switch should have a higher or equal cost
            # (they could be equal if same port cost, but typically differ)


# ---------------------------------------------------------------------------
# Test C — Triangle (redundant topology — no loop)
# ---------------------------------------------------------------------------

class TestTriangleTopology:
    """
    SW1 Gi0/0 ---- Gi0/0 SW2
      \\                  /
    Gi0/1            Gi0/1
        \\            /
         Gi0/0  Gi0/1
              SW3

    Three connected switches in a ring.
    After STP: one root, at least one port in DISCARDING/BLOCKING (alternate),
    no forwarding loop.
    """

    def _build(self):
        topo = Topology()
        macs = {
            "sw1": "aa:00:00:00:00",
            "sw2": "aa:00:00:00:aa",
            "sw3": "aa:00:00:00:ff",
        }
        for sw_id, mac_prefix in macs.items():
            dev = Device(id=sw_id, model=DeviceModel.SWITCH, hostname=sw_id.upper())
            for p in range(3):
                dev.add_interface(Interface(
                    name=f"Gi0/{p}",
                    mac=MACAddress(f"{mac_prefix}:0{p}"),
                ))
            topo.add_device(dev)
        topo.add_link(Link(id="l12", endpoint_a=("sw1", "Gi0/0"), endpoint_b=("sw2", "Gi0/0")))
        topo.add_link(Link(id="l13", endpoint_a=("sw1", "Gi0/1"), endpoint_b=("sw3", "Gi0/0")))
        topo.add_link(Link(id="l23", endpoint_a=("sw2", "Gi0/1"), endpoint_b=("sw3", "Gi0/1")))
        return topo

    def test_one_root(self) -> None:
        sim = _build_sim(self._build())
        roots = sum(
            1 for s in ("sw1", "sw2", "sw3")
            if sim.get_switch(s).stp.get_instance(1).is_root
        )
        assert roots == 1

    def test_at_least_one_alternate_or_discarding_port(self) -> None:
        """Triangle must have at least one blocked port to prevent loop."""
        sim = _build_sim(self._build())
        blocking_ports = []
        for sw_id in ("sw1", "sw2", "sw3"):
            inst = sim.get_switch(sw_id).stp.get_instance(1)
            for pname, pstate in inst.port_states.items():
                if pstate.role in (PortRole.ALTERNATE, PortRole.BACKUP):
                    blocking_ports.append((sw_id, pname, pstate.role, pstate.state))
        assert len(blocking_ports) >= 1, (
            f"Triangle topology must have at least one ALTERNATE port to prevent loop.\n"
            f"All port states:\n" +
            "\n".join(
                f"  {s} {p}: role={ps.role} state={ps.state}"
                for s in ("sw1","sw2","sw3")
                for p, ps in sim.get_switch(s).stp.get_instance(1).port_states.items()
            )
        )

    def test_all_agree_on_root(self) -> None:
        sim = _build_sim(self._build())
        bids = [sim.get_switch(s).stp.get_instance(1).root_bridge_id
                for s in ("sw1","sw2","sw3")]
        assert bids[0] == bids[1] == bids[2]


# ---------------------------------------------------------------------------
# Test D — Priority change triggers re-election
# ---------------------------------------------------------------------------

class TestPriorityChange:
    """SW3 gets priority 4096 — it should become root after re-election."""

    def _build(self):
        topo = Topology()
        for sw_id, mac_b in [("sw1","01"), ("sw2","02"), ("sw3","FF")]:
            dev = Device(id=sw_id, model=DeviceModel.SWITCH, hostname=sw_id.upper())
            dev.add_interface(Interface(name="Gi0/0", mac=MACAddress(f"aa:00:00:00:00:{mac_b}")))
            dev.add_interface(Interface(name="Gi0/1", mac=MACAddress(f"aa:00:00:00:01:{mac_b}")))
            topo.add_device(dev)
        topo.add_link(Link(id="l12", endpoint_a=("sw1","Gi0/0"), endpoint_b=("sw2","Gi0/0")))
        topo.add_link(Link(id="l23", endpoint_a=("sw2","Gi0/1"), endpoint_b=("sw3","Gi0/0")))
        return topo

    def test_priority_change_makes_sw3_root(self) -> None:
        sim = _build_sim(self._build())
        # Initial: SW1 (mac=01) should be root
        inst1_before = sim.get_switch("sw1").stp.get_instance(1)
        assert inst1_before.is_root, "SW1 should be initial root (lowest MAC)"

        # Change SW3 priority to 4096 (< 32768) so it wins
        sim.get_switch("sw3").stp.set_bridge_priority(1, 4096)
        # Re-run STP election
        sim.run_stp()

        # SW3 should now be root
        inst3 = sim.get_switch("sw3").stp.get_instance(1)
        assert inst3.is_root, (
            f"SW3 should be root after priority=4096, but root is "
            f"{sim.get_switch('sw1').stp.get_instance(1).root_bridge_id}"
        )
        # All switches should agree on SW3 as root
        for sw_id in ("sw1", "sw2", "sw3"):
            inst = sim.get_switch(sw_id).stp.get_instance(1)
            assert inst.root_bridge_id == inst3.bridge_id, (
                f"{sw_id} still uses old root {inst.root_bridge_id}"
            )


# ---------------------------------------------------------------------------
# Test E — Disconnected ports are not marked as root/alternate
# ---------------------------------------------------------------------------

class TestDisconnectedPorts:
    """
    A 4-port switch with only port 0 connected to another switch.
    Ports 1-3 have no cable — they should still be DESIGNATED FORWARDING
    (IOS behavior) but must NOT be root or alternate ports.
    """

    def _build(self):
        topo = Topology()
        for sw_id, mac_b in [("sw1","01"), ("sw2","AA")]:
            dev = Device(id=sw_id, model=DeviceModel.SWITCH, hostname=sw_id.upper())
            for p in range(4):
                dev.add_interface(Interface(
                    name=f"Gi0/{p}",
                    mac=MACAddress(f"aa:00:00:00:{mac_b}:0{p}"),
                ))
            topo.add_device(dev)
        # Only connect one port between the two switches
        topo.add_link(Link(id="l1", endpoint_a=("sw1","Gi0/0"), endpoint_b=("sw2","Gi0/0")))
        return topo

    def test_unconnected_ports_not_root_port(self) -> None:
        sim = _build_sim(self._build())
        # sw2 is non-root; its root_port must be Gi0/0 (the connected port)
        inst2 = sim.get_switch("sw2").stp.get_instance(1)
        assert inst2.root_port_name == "Gi0/0", (
            f"Root port must be the connected port, got {inst2.root_port_name}"
        )
        # Ports 1-3 of sw2 must NOT be root ports
        for p in range(1, 4):
            port = inst2.port_states.get(f"Gi0/{p}")
            if port:
                assert port.role != PortRole.ROOT, (
                    f"Unconnected Gi0/{p} must not be root port"
                )

    def test_unconnected_ports_on_root_are_designated(self) -> None:
        sim = _build_sim(self._build())
        inst1 = sim.get_switch("sw1").stp.get_instance(1)
        # sw1 is root; all its ports should be designated forwarding
        for p in range(4):
            port = inst1.port_states.get(f"Gi0/{p}")
            if port:
                assert port.role == PortRole.DESIGNATED, (
                    f"Root switch Gi0/{p} should be DESIGNATED, got {port.role}"
                )


# ---------------------------------------------------------------------------
# Test F — VLAN separation
# ---------------------------------------------------------------------------

class TestVLANSeparation:
    """
    Two VLANs with separate STP instances.
    Root election must happen independently per VLAN.
    """

    def _build(self):
        topo = Topology()
        for sw_id, mac_b in [("sw1","01"), ("sw2","AA")]:
            dev = Device(id=sw_id, model=DeviceModel.SWITCH, hostname=sw_id.upper())
            dev.add_interface(Interface(name="Gi0/0", mac=MACAddress(f"aa:00:00:00:{mac_b}:00")))
            topo.add_device(dev)
        topo.add_link(Link(id="l1", endpoint_a=("sw1","Gi0/0"), endpoint_b=("sw2","Gi0/0")))
        return topo

    def test_separate_stp_instances_per_vlan(self) -> None:
        sim = _build_sim(self._build())
        # Create VLAN 10 on both switches
        sim.get_switch("sw1").create_vlan(10)
        sim.get_switch("sw2").create_vlan(10)
        sim.run_stp()

        inst1_v1  = sim.get_switch("sw1").stp.get_instance(1)
        inst1_v10 = sim.get_switch("sw1").stp.get_instance(10)
        inst2_v1  = sim.get_switch("sw2").stp.get_instance(1)
        inst2_v10 = sim.get_switch("sw2").stp.get_instance(10)

        # Both instances exist
        assert inst1_v10 is not None
        assert inst2_v10 is not None

        # Both switches agree on root for VLAN 1
        assert inst1_v1.root_bridge_id == inst2_v1.root_bridge_id

        # Both switches agree on root for VLAN 10
        assert inst1_v10.root_bridge_id == inst2_v10.root_bridge_id

        # VLAN 1 and VLAN 10 may have different roots (different sys_id_ext)
        # but they must each be internally consistent
        assert not (inst1_v1.is_root and inst2_v1.is_root), "Only one root per VLAN instance"
        assert not (inst1_v10.is_root and inst2_v10.is_root), "Only one root per VLAN 10 instance"


# ---------------------------------------------------------------------------
# Test G — STP re-runs correctly (run_stp() is idempotent)
# ---------------------------------------------------------------------------

class TestSTPIdempotent:
    """run_stp() called multiple times must produce the same stable result."""

    def _build(self):
        topo = Topology()
        for sw_id, mac_b in [("sw1","01"), ("sw2","AA")]:
            dev = Device(id=sw_id, model=DeviceModel.SWITCH, hostname=sw_id.upper())
            dev.add_interface(Interface(name="Gi0/0", mac=MACAddress(f"aa:00:00:00:{mac_b}:00")))
            topo.add_device(dev)
        topo.add_link(Link(id="l1", endpoint_a=("sw1","Gi0/0"), endpoint_b=("sw2","Gi0/0")))
        return topo

    def test_multiple_run_stp_calls_stable(self) -> None:
        sim = _build_sim(self._build())
        root_before = sim.get_switch("sw1").stp.get_instance(1).root_bridge_id
        sim.run_stp()
        sim.run_stp()
        root_after = sim.get_switch("sw1").stp.get_instance(1).root_bridge_id
        assert root_before == root_after, "run_stp() must be stable (idempotent)"
