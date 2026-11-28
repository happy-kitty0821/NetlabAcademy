"""
``spanning-tree vlan <range>`` takes IOS VLAN lists (1-100, 1,3-5,7), and
``?`` help walks through the argument the way IOS does.
"""

from __future__ import annotations

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.simulation import Simulation
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
    sim = Simulation(topo, seed=1)
    sessions = {}
    for dev in ("sw1", "sw2"):
        s = CLISession(device_id=dev, simulation=sim)
        s.execute("enable")
        s.execute("configure terminal")
        for vlan in (10, 20):
            s.execute(f"vlan {vlan}")
            s.execute("exit")
        s.execute("interface FastEthernet0/1")
        s.execute("switchport mode trunk")
        s.execute("exit")
        sessions[dev] = s
    return sim, sessions


def _prio(sim, dev, vlan):
    return sim.get_switch(dev).stp.get_instance(vlan).bridge_id.priority


def test_root_primary_over_a_range(lab):
    sim, s = lab
    assert s["sw2"].execute("spanning-tree vlan 1-100 root primary") == ""
    for vlan in (1, 10, 20):
        assert _prio(sim, "sw2", vlan) == 24576
        assert sim.get_switch("sw2").stp.get_instance(vlan).is_root
        assert not sim.get_switch("sw1").stp.get_instance(vlan).is_root


def test_priority_list_and_running_config(lab):
    sim, s = lab
    assert s["sw1"].execute("spanning-tree vlan 1,10 priority 4096") == ""
    assert s["sw1"].execute("spanning-tree vlan 20,200-300 pri 8192") == ""
    assert (_prio(sim, "sw1", 1), _prio(sim, "sw1", 10), _prio(sim, "sw1", 20)) == (4096, 4096, 8192)
    run = s["sw1"].execute("do show running-config")
    assert "spanning-tree vlan 1,10 priority 4096" in run
    assert "spanning-tree vlan 20,200-300 priority 8192" in run


def test_range_priority_applies_to_vlans_created_later(lab):
    sim, s = lab
    s["sw1"].execute("spanning-tree vlan 1-4094 priority 4096")
    assert sim.get_switch("sw1").stp.get_instance(500) is None   # no tree built up front
    s["sw1"].execute("vlan 500")
    s["sw1"].execute("exit")
    assert _prio(sim, "sw1", 500) == 4096
    run = s["sw1"].execute("do show running-config")
    assert "spanning-tree vlan 1-4094 priority 4096" in run


def test_no_priority_resets_the_range(lab):
    sim, s = lab
    s["sw1"].execute("spanning-tree vlan 1-20 priority 4096")
    assert s["sw1"].execute("no spanning-tree vlan 10-20 priority") == ""
    assert (_prio(sim, "sw1", 1), _prio(sim, "sw1", 10), _prio(sim, "sw1", 20)) == (4096, 32768, 32768)
    run = s["sw1"].execute("do show running-config")
    assert "spanning-tree vlan 1-9 priority 4096" in run
    assert "spanning-tree vlan 1-20" not in run


def test_bad_values_are_rejected(lab):
    _, s = lab
    assert "Bridge Priority must be in increments of 4096" in s["sw1"].execute(
        "spanning-tree vlan 1-100 priority 5000")
    for bad in ("spanning-tree vlan 1-100root primary", "spanning-tree vlan 0 priority 4096",
                "spanning-tree vlan 1-5000 priority 4096", "spanning-tree vlan 5-1 priority 4096",
                "spanning-tree vlan 1 priority 70000"):
        assert "% Invalid input detected" in s["sw1"].execute(bad), bad
    assert s["sw1"].execute("spanning-tree vlan 1-100 root") == "% Incomplete command."


def test_help_walks_the_arguments(lab):
    _, s = lab
    assert s["sw1"].execute("spanning-tree vlan ?") == "  WORD  vlan range, example: 1,3-5,7,9-11"
    opts = s["sw1"].execute("spanning-tree vlan 1-100 ?").splitlines()
    assert [l.split()[0] for l in opts] == [
        "forward-time", "hello-time", "max-age", "priority", "root", "<cr>"]
    root = s["sw1"].execute("spanning-tree vlan 1-100 root ?")
    assert [l.split()[0] for l in root.splitlines()] == ["primary", "secondary"]
    assert "<0-61440>" in s["sw1"].execute("spanning-tree vlan 1-100 priority ?")
    assert s["sw1"].execute("spanning-tree vlan 1-100 priority 4096 ?") == "  <cr>"
    assert "% Invalid input detected" in s["sw1"].execute("spanning-tree vlan 1-100root ?")


def test_interface_cost_over_a_range(lab):
    sim, s = lab
    s["sw2"].execute("interface FastEthernet0/1")
    assert s["sw2"].execute("spanning-tree vlan 10,20 cost 100") == ""
    stp = sim.get_switch("sw2").stp
    assert stp.get_instance(10).port_states["Fa0/1"].path_cost == 100
    assert stp.get_instance(20).port_states["Fa0/1"].path_cost == 100
    assert stp.get_instance(1).port_states["Fa0/1"].path_cost != 100


def test_show_spanning_tree_vlan_list(lab):
    _, s = lab
    out = s["sw1"].execute("do show spanning-tree vlan 1,10")
    assert "VLAN0001" in out and "VLAN0010" in out and "VLAN0020" not in out
    assert (s["sw1"].execute("do show spanning-tree vlan 300-310")
            == "Spanning tree instance(s) for vlan 300-310 does not exist.")
