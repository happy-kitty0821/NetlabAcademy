"""
tests/test_stp_port_registration.py
------------------------------------
Tests for STP port registration on switch init, protocol name consistency,
and forwarding/blocking counts in show spanning-tree output.
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.simulation import Simulation
from simulator_core.stp import PortState
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel


def _mac(seed: int) -> MACAddress:
    return MACAddress.generate(random.Random(seed))


def _build_switch_topology(
    iface_names: list[str],
    switch_id: str = "sw1",
    hostname: str = "SW1",
) -> tuple[Topology, str]:
    """Build a single-switch topology with the given interface names."""
    topo = Topology()
    sw = Device(id=switch_id, model=DeviceModel.SWITCH, hostname=hostname)
    for i, name in enumerate(iface_names):
        sw.add_interface(Interface(name=name, mac=_mac(i + 1)))
    topo.add_device(sw)
    return topo, switch_id


def _build_two_switch_topology() -> tuple[Topology, str, str]:
    """
    SW1 ── SW2  (trunk link Gi0/1 ↔ Gi0/0, two host ports on each).
    Matches the helper from test_stp.py for consistency.
    """
    topo = Topology()

    sw1 = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
    sw1.add_interface(Interface(name="Gi0/0", mac=_mac(1)))
    sw1.add_interface(Interface(name="Gi0/1", mac=_mac(2)))
    sw1.add_interface(Interface(name="Gi0/2", mac=_mac(3)))
    sw1.add_interface(Interface(name="Gi0/3", mac=_mac(4)))

    sw2 = Device(id="sw2", model=DeviceModel.SWITCH, hostname="SW2")
    sw2.add_interface(Interface(name="Gi0/0", mac=_mac(5)))
    sw2.add_interface(Interface(name="Gi0/1", mac=_mac(6)))
    sw2.add_interface(Interface(name="Gi0/2", mac=_mac(7)))
    sw2.add_interface(Interface(name="Gi0/3", mac=_mac(8)))

    topo.add_device(sw1)
    topo.add_device(sw2)
    topo.add_link(
        Link(
            id="trunk-sw1-sw2",
            endpoint_a=("sw1", "Gi0/1"),
            endpoint_b=("sw2", "Gi0/0"),
        )
    )
    return topo, "sw1", "sw2"


# ---------------------------------------------------------------------------
# 1. STP ports registered on switch init
# ---------------------------------------------------------------------------


class TestSTPPortRegistrationOnInit:
    def test_stp_ports_registered_on_switch_init(self) -> None:
        """
        A switch with 3 Gi interfaces should have all 3 registered in
        port_states for VLAN 1 immediately after Simulation() builds it.
        """
        topo, sw_id = _build_switch_topology(
            ["Gi0/0", "Gi0/1", "Gi0/2"], switch_id="sw1"
        )
        sim = Simulation(topo, seed=42)
        switch = sim.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        assert inst is not None, "VLAN 1 STP instance must exist"
        assert len(inst.port_states) == 3, (
            f"Expected 3 ports registered, got {len(inst.port_states)}: "
            f"{list(inst.port_states.keys())}"
        )

    def test_port_ids_are_stable_and_unique(self) -> None:
        """Every registered port should have a unique non-zero port number."""
        topo, sw_id = _build_switch_topology(
            ["Gi0/0", "Gi0/1", "Gi0/2"], switch_id="sw1"
        )
        sim = Simulation(topo, seed=42)
        switch = sim.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        port_nums = [p.port_id.number for p in inst.port_states.values() if p.port_id]
        assert len(port_nums) == len(set(port_nums)), "Port numbers must be unique"
        assert all(n > 0 for n in port_nums), "Port numbers must be > 0"

    def test_svi_excluded_from_stp(self) -> None:
        """SVI interfaces (Vlan*) must not be registered with STP."""
        topo = Topology()
        sw = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
        sw.add_interface(Interface(name="Gi0/0", mac=_mac(1)))
        sw.add_interface(Interface(name="Vlan1", mac=_mac(2)))
        topo.add_device(sw)
        sim = Simulation(topo, seed=42)
        switch = sim.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        assert "Vlan1" not in inst.port_states
        assert "Gi0/0" in inst.port_states

    def test_register_interface_with_stp_adds_to_all_instances(self) -> None:
        """register_interface_with_stp() registers a port in all VLAN instances."""
        topo, sw_id = _build_switch_topology(["Gi0/0", "Gi0/1"], switch_id="sw1")
        sim = Simulation(topo, seed=42)
        switch = sim.get_switch("sw1")
        # Create a second VLAN instance
        switch.create_vlan(10, "engineering")
        # Add a new interface to the device directly then register it.
        new_iface = Interface(name="Gi0/2", mac=_mac(99))
        switch._device.add_interface(new_iface)
        switch.register_interface_with_stp("Gi0/2")
        for vlan_id in (1, 10):
            inst = switch.stp.get_instance(vlan_id)
            assert "Gi0/2" in inst.port_states, (
                f"Gi0/2 must be in VLAN {vlan_id} port_states"
            )


# ---------------------------------------------------------------------------
# 2. show spanning-tree displays interface lines
# ---------------------------------------------------------------------------


class TestShowSpanningTreePortDisplay:
    def _make_session(self, device_id: str = "sw1") -> CLISession:
        topo, sw1_id, sw2_id = _build_two_switch_topology()
        sim = Simulation(topo, seed=42)
        s = CLISession(device_id=device_id, simulation=sim)
        s.execute("enable")
        return s

    def test_show_spanning_tree_shows_ports(self) -> None:
        """
        show spanning-tree must list at least one interface name line
        below the '---' header separator.
        """
        s = self._make_session("sw1")
        out = s.execute("show spanning-tree")
        assert "---" in out, "Expected the column separator line"
        # Everything after the first separator should contain interface lines
        separator_idx = out.index("---")
        after_sep = out[separator_idx + 3:].strip()
        assert after_sep, (
            "Expected interface entries below the separator, got nothing.\n"
            f"Full output:\n{out}"
        )

    def test_show_spanning_tree_contains_interface_names(self) -> None:
        """Port lines for the connected interface (Gi0/1) must appear."""
        s = self._make_session("sw1")
        out = s.execute("show spanning-tree")
        assert "Gi0/1" in out, (
            f"Expected Gi0/1 in spanning-tree output:\n{out}"
        )

    def test_show_spanning_tree_all_four_ports_on_sw1(self) -> None:
        """SW1 has 4 interfaces; all 4 must appear in spanning-tree output."""
        s = self._make_session("sw1")
        out = s.execute("show spanning-tree")
        for iface in ("Gi0/0", "Gi0/1", "Gi0/2", "Gi0/3"):
            assert iface in out, (
                f"Expected {iface} in spanning-tree output:\n{out}"
            )


# ---------------------------------------------------------------------------
# 3. show spanning-tree summary forwarding count > 0
# ---------------------------------------------------------------------------


class TestShowSpanningTreeSummary:
    def _make_session(self, device_id: str = "sw1") -> CLISession:
        topo, sw1_id, sw2_id = _build_two_switch_topology()
        sim = Simulation(topo, seed=42)
        s = CLISession(device_id=device_id, simulation=sim)
        s.execute("enable")
        return s

    def test_show_spanning_tree_summary_counts(self) -> None:
        """
        show spanning-tree summary must report forwarding > 0 for a switch
        that has registered ports.
        """
        s = self._make_session("sw1")
        out = s.execute("show spanning-tree summary")
        # Find the VLAN0001 data line (starts with VLAN0001, not "Root bridge for:")
        lines = out.splitlines()
        vlan_line = next(
            (l for l in lines if l.strip().startswith("VLAN0001") and len(l.split()) >= 5),
            None,
        )
        assert vlan_line is not None, f"Expected VLAN0001 data line in summary:\n{out}"
        # Columns: Name Blocking Listening Learning Forwarding Active
        parts = vlan_line.split()
        # parts[4] is Forwarding count
        assert len(parts) >= 5, f"Expected ≥5 columns in VLAN line: {vlan_line!r}"
        forwarding_count = int(parts[4])
        assert forwarding_count > 0, (
            f"Expected forwarding count > 0, got {forwarding_count}.\n"
            f"Full summary:\n{out}"
        )

    def test_show_spanning_tree_summary_active_matches_port_count(self) -> None:
        """Active port count in summary must equal number of physical interfaces."""
        s = self._make_session("sw1")
        out = s.execute("show spanning-tree summary")
        lines = out.splitlines()
        vlan_line = next(
            (l for l in lines if l.strip().startswith("VLAN0001") and len(l.split()) >= 6),
            None,
        )
        assert vlan_line is not None, f"Expected VLAN0001 data line in summary:\n{out}"
        parts = vlan_line.split()
        active_count = int(parts[5])
        # SW1 has 4 physical interfaces
        assert active_count == 4, (
            f"Expected 4 active ports, got {active_count}.\nLine: {vlan_line!r}"
        )


# ---------------------------------------------------------------------------
# 4. STP protocol string consistency
# ---------------------------------------------------------------------------


class TestSTPProtocolStringConsistency:
    def _make_session(self) -> CLISession:
        topo, sw_id = _build_switch_topology(["Gi0/0", "Gi0/1"], switch_id="sw1")
        sim = Simulation(topo, seed=42)
        s = CLISession(device_id="sw1", simulation=sim)
        s.execute("enable")
        return s

    def test_stp_protocol_string_consistent(self) -> None:
        """
        show spanning-tree must say 'rapid-pvst' (not 'rst' or 'rstp').
        show spanning-tree summary must say 'Rapid PVST+'.
        """
        s = self._make_session()
        st_out = s.execute("show spanning-tree")
        assert "rapid-pvst" in st_out, (
            f"Expected 'rapid-pvst' in show spanning-tree output:\n{st_out}"
        )
        assert "rstp" not in st_out.lower().replace("rapid-pvst", ""), (
            f"'rstp' found in output (old incorrect value):\n{st_out}"
        )

        summary_out = s.execute("show spanning-tree summary")
        assert "Rapid PVST+" in summary_out, (
            f"Expected 'Rapid PVST+' in show spanning-tree summary:\n{summary_out}"
        )

    def test_pvst_mode_shows_pvst(self) -> None:
        """After 'spanning-tree mode pvst', show spanning-tree must say 'pvst'."""
        s = self._make_session()
        s.execute("configure terminal")
        s.execute("spanning-tree mode pvst")
        s.execute("end")
        out = s.execute("show spanning-tree")
        assert "protocol pvst" in out, (
            f"Expected 'protocol pvst' in output:\n{out}"
        )


# ---------------------------------------------------------------------------
# 5. Access ports included in STP
# ---------------------------------------------------------------------------


class TestAccessPortInSTP:
    def test_access_port_in_stp(self) -> None:
        """
        A switch with one access port (VLAN 1) and one trunk port must have
        both in inst.port_states after init.
        """
        topo = Topology()
        sw = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
        sw.add_interface(Interface(name="Gi0/0", mac=_mac(1)))   # access
        sw.add_interface(Interface(name="Gi0/1", mac=_mac(2)))   # will set trunk
        topo.add_device(sw)
        sim = Simulation(topo, seed=42)
        switch = sim.get_switch("sw1")

        # Configure one as trunk
        switch.set_trunk_mode("Gi0/1")

        inst = switch.stp.get_instance(1)
        assert "Gi0/0" in inst.port_states, "Access port Gi0/0 must be in STP"
        assert "Gi0/1" in inst.port_states, "Trunk port Gi0/1 must be in STP"

    def test_access_port_in_different_vlan_registered(self) -> None:
        """
        When VLAN 10 is created and an access port is assigned to it,
        that port must still appear in VLAN 1's port_states (registered
        at init time) and in VLAN 10's port_states (created later).
        """
        topo = Topology()
        sw = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
        sw.add_interface(Interface(name="Gi0/0", mac=_mac(1)))
        sw.add_interface(Interface(name="Gi0/1", mac=_mac(2)))
        topo.add_device(sw)
        sim = Simulation(topo, seed=42)
        switch = sim.get_switch("sw1")

        # Create VLAN 10 and assign Gi0/0 to it
        switch.create_vlan(10, "data")
        switch.set_port_vlan("Gi0/0", 10)

        # Both ports were registered at init time for VLAN 1
        inst1 = switch.stp.get_instance(1)
        assert "Gi0/0" in inst1.port_states
        assert "Gi0/1" in inst1.port_states

        # VLAN 10 instance must have both ports inherited from VLAN 1
        inst10 = switch.stp.get_instance(10)
        assert inst10 is not None, "VLAN 10 STP instance must exist"
        assert "Gi0/0" in inst10.port_states, (
            "Gi0/0 must be in VLAN 10 port_states (inherited from init-time registration)"
        )
        assert "Gi0/1" in inst10.port_states, (
            "Gi0/1 must be in VLAN 10 port_states (inherited from init-time registration)"
        )


# ---------------------------------------------------------------------------
# 6. Root bridge has all ports forwarding
# ---------------------------------------------------------------------------


class TestSTPSummaryForwardingNonzeroOnRoot:
    def test_stp_summary_forwarding_nonzero_on_root(self) -> None:
        """
        A switch that is root bridge must report all ports forwarding in
        show spanning-tree summary (forwarding count > 0).
        """
        # Build a single switch — it is always root (no peers)
        topo, sw_id = _build_switch_topology(
            ["Gi0/0", "Gi0/1", "Gi0/2"], switch_id="sw1"
        )
        sim = Simulation(topo, seed=42)
        s = CLISession(device_id="sw1", simulation=sim)
        s.execute("enable")

        out = s.execute("show spanning-tree summary")
        lines = out.splitlines()
        vlan_line = next(
            (l for l in lines if l.strip().startswith("VLAN0001") and len(l.split()) >= 5),
            None,
        )
        assert vlan_line is not None, f"Expected VLAN0001 data line:\n{out}"
        parts = vlan_line.split()
        forwarding = int(parts[4])
        assert forwarding > 0, (
            f"Root bridge should have forwarding ports > 0, got {forwarding}.\n"
            f"Full summary:\n{out}"
        )

    def test_root_bridge_all_ports_forwarding_state(self) -> None:
        """Every port on a standalone root bridge should be in FORWARDING state."""
        topo, sw_id = _build_switch_topology(
            ["Gi0/0", "Gi0/1", "Gi0/2"], switch_id="sw1"
        )
        sim = Simulation(topo, seed=42)
        switch = sim.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        for name, port in inst.port_states.items():
            assert port.state == PortState.FORWARDING, (
                f"Port {name} expected FORWARDING, got {port.state}"
            )
