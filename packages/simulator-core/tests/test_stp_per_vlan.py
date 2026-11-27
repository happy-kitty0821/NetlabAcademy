"""
PVST+: each VLAN has its own spanning tree, built only over links that
carry that VLAN (access VLAN on both ends, or allowed on both trunk ends).

Topology: two switches, two cables.

    SW1 Fa0/1 ──── Fa0/1 SW2
    SW1 Fa0/2 ──── Fa0/2 SW2

SW1 has the lower MAC.
"""

from __future__ import annotations

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.simulation import Simulation
from simulator_core.stp import PortRole
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel


def _switch(dev_id: str, base: int) -> Device:
    dev = Device(id=dev_id, model=DeviceModel.SWITCH, hostname=dev_id.upper())
    for n in range(1, 5):
        dev.add_interface(Interface(name=f"Fa0/{n}", mac=MACAddress(f"aa:00:00:00:{base:02x}:{n:02x}")))
    return dev


@pytest.fixture()
def lab():
    topo = Topology()
    topo.add_device(_switch("sw1", 0x01))
    topo.add_device(_switch("sw2", 0x02))
    topo.add_link(Link(id="l1", endpoint_a=("sw1", "Fa0/1"), endpoint_b=("sw2", "Fa0/1")))
    topo.add_link(Link(id="l2", endpoint_a=("sw1", "Fa0/2"), endpoint_b=("sw2", "Fa0/2")))
    sim = Simulation(topo, seed=1)
    sessions = {}
    for dev in ("sw1", "sw2"):
        s = CLISession(device_id=dev, simulation=sim)
        s.execute("enable")
        sessions[dev] = s
    return sim, sessions


def _config(session: CLISession, *lines: str, iface: str | None = None) -> list[str]:
    out = [session.execute("configure terminal")]
    if iface:
        out.append(session.execute(f"interface {iface}"))
    out += [session.execute(line) for line in lines]
    session.execute("end")
    return out


def _both(s, *lines, iface=None):
    for dev in ("sw1", "sw2"):
        _config(s[dev], *lines, iface=iface)


def _trunk_both_links(s, *extra):
    for port in ("FastEthernet0/1", "FastEthernet0/2"):
        _both(s, "switchport mode trunk", *extra, iface=port)


def _inst(sim, dev, vlan):
    return sim.get_switch(dev).stp.get_instance(vlan)


def _blocked(sim, dev, vlan) -> list[str]:
    inst = _inst(sim, dev, vlan)
    return sorted(n for n, p in inst.port_states.items() if p.role == PortRole.ALTERNATE)


def test_trunks_load_balance_with_per_vlan_roots(lab):
    """Classic PVST+ lab: a different root per VLAN blocks a different side."""
    sim, s = lab
    _both(s, "vlan 10", "vlan 20")
    _trunk_both_links(s)
    _config(s["sw1"], "spanning-tree vlan 10 root primary")
    _config(s["sw2"], "spanning-tree vlan 20 root primary")

    assert _inst(sim, "sw1", 10).is_root and not _inst(sim, "sw2", 10).is_root
    assert _inst(sim, "sw2", 20).is_root and not _inst(sim, "sw1", 20).is_root
    assert _blocked(sim, "sw2", 10) == ["Fa0/2"] and _blocked(sim, "sw1", 10) == []
    assert _blocked(sim, "sw1", 20) == ["Fa0/2"] and _blocked(sim, "sw2", 20) == []
    # Data plane follows the per-VLAN state
    stp1 = sim.get_switch("sw1").stp
    assert stp1.is_port_forwarding("Fa0/2", 10)
    assert not stp1.is_port_forwarding("Fa0/2", 20)


def test_port_priority_per_vlan_splits_the_links(lab):
    """Same root for both VLANs, but each VLAN prefers a different cable."""
    sim, s = lab
    _both(s, "vlan 10", "vlan 20")
    _trunk_both_links(s)
    _config(s["sw1"], "spanning-tree vlan 20 port-priority 64", iface="FastEthernet0/2")
    assert _inst(sim, "sw2", 10).root_port_name == "Fa0/1"
    assert _inst(sim, "sw2", 20).root_port_name == "Fa0/2"


def test_trunk_allowed_list_limits_a_vlans_tree(lab):
    sim, s = lab
    _both(s, "vlan 10", "vlan 20")
    _trunk_both_links(s)
    # VLAN 20 is not allowed on the second cable: its tree has no loop.
    _both(s, "switchport trunk allowed vlan 1,10", iface="FastEthernet0/2")
    assert _blocked(sim, "sw2", 10) == ["Fa0/2"]
    assert _blocked(sim, "sw2", 20) == []
    assert _inst(sim, "sw2", 20).root_port_name == "Fa0/1"
    show = s["sw2"].execute("show spanning-tree vlan 20")
    assert "Fa0/1" in show and "Fa0/2" not in show


def test_access_links_in_different_vlans_do_not_loop(lab):
    sim, s = lab
    _both(s, "vlan 10", "vlan 20")
    _both(s, "switchport access vlan 10", iface="FastEthernet0/1")
    _both(s, "switchport access vlan 20", iface="FastEthernet0/2")
    for vlan in (10, 20):
        assert _blocked(sim, "sw1", vlan) == [] and _blocked(sim, "sw2", vlan) == []
        assert _inst(sim, "sw1", vlan).is_root
        assert not _inst(sim, "sw2", vlan).is_root
    # No up port carries VLAN 1 any more
    assert (s["sw2"].execute("show spanning-tree vlan 1")
            == "Spanning tree instance(s) for vlan 1 does not exist.")


def test_vlan_needs_to_exist_on_both_switches(lab):
    sim, s = lab
    _config(s["sw1"], "vlan 10")
    _trunk_both_links(s)
    # SW2 has no VLAN 10, so SW1 is alone in VLAN 10's tree
    assert _inst(sim, "sw1", 10).is_root
    assert _blocked(sim, "sw1", 10) == []
    _config(s["sw2"], "vlan 10")
    assert _blocked(sim, "sw2", 10) == ["Fa0/2"]
    _config(s["sw2"], "no vlan 10")
    assert _blocked(sim, "sw1", 10) == [] and _blocked(sim, "sw2", 1) == ["Fa0/2"]


def test_show_lists_only_active_vlans(lab):
    _, s = lab
    _both(s, "vlan 10", "vlan 20")
    _trunk_both_links(s, "switchport trunk allowed vlan 1,10")
    out = s["sw2"].execute("show spanning-tree")
    assert "VLAN0001" in out and "VLAN0010" in out and "VLAN0020" not in out
    assert (s["sw2"].execute("show spanning-tree vlan 30")
            == "Spanning tree instance(s) for vlan 30 does not exist.")
    summary = s["sw2"].execute("show spanning-tree summary")
    rows = {l.split()[0]: l.split()[1:] for l in summary.splitlines() if l.startswith("VLAN")}
    assert set(rows) == {"VLAN0001", "VLAN0010"}
    assert rows["VLAN0010"] == ["1", "0", "0", "1", "2"]
    assert "2 vlans" in summary


def test_isolated_switch_has_no_instance(lab):
    sim, s = lab
    sim.remove_link("l1")
    sim.remove_link("l2")
    assert s["sw1"].execute("show spanning-tree") == "No spanning tree instance exists."
