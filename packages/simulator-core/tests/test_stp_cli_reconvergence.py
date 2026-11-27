"""
STP changes made from the CLI re-run the election across the whole network.

Topology (two cables between two switches, as in a typical redundancy lab):

    SW1 Fa0/1 ──── Fa0/1 SW2
    SW1 Fa0/2 ──── Fa0/2 SW2

SW1 has the lower MAC, so with default priorities it is the root and SW2
blocks Fa0/2.
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
    outputs = [session.execute("configure terminal")]
    if iface:
        outputs.append(session.execute(f"interface {iface}"))
    outputs += [session.execute(line) for line in lines]
    session.execute("end")
    return outputs


def _inst(sim: Simulation, dev: str):
    return sim.get_switch(dev).stp.get_instance(1)


def _role(sim: Simulation, dev: str, port: str) -> PortRole:
    return _inst(sim, dev).port_states[port].role


def test_default_election(lab):
    sim, _ = lab
    assert _inst(sim, "sw1").is_root
    assert _inst(sim, "sw2").root_port_name == "Fa0/1"
    assert _role(sim, "sw2", "Fa0/2") == PortRole.ALTERNATE


def test_root_secondary_on_root_is_seen_by_neighbour(lab):
    """The user's case: SW2 must learn the root's new priority."""
    sim, s = lab
    _config(s["sw1"], "spanning-tree vlan 1 root secondary")
    assert _inst(sim, "sw1").bridge_id.priority == 28672
    assert _inst(sim, "sw1").is_root
    assert _inst(sim, "sw2").root_bridge_id.bridge_priority == 28673
    out = s["sw2"].execute("show spanning-tree vlan 1")
    assert "Root ID    Priority    28673" in out
    assert "Altn BLK" in out


def test_root_primary_on_other_switch_moves_the_root(lab):
    sim, s = lab
    _config(s["sw2"], "spanning-tree vlan 1 root primary")
    assert _inst(sim, "sw2").bridge_id.priority == 24576
    assert _inst(sim, "sw2").is_root
    assert not _inst(sim, "sw1").is_root, "two root bridges would loop"
    assert _inst(sim, "sw1").root_port_name == "Fa0/1"
    assert _role(sim, "sw1", "Fa0/2") == PortRole.ALTERNATE
    assert _role(sim, "sw2", "Fa0/1") == PortRole.DESIGNATED
    assert _role(sim, "sw2", "Fa0/2") == PortRole.DESIGNATED


def test_root_primary_goes_below_a_lower_root(lab):
    """IOS: when the root is already at or below 24576, go 4096 under it."""
    sim, s = lab
    _config(s["sw1"], "spanning-tree vlan 1 priority 24576")
    _config(s["sw2"], "spanning-tree vlan 1 root primary")
    assert _inst(sim, "sw2").bridge_id.priority == 20480
    assert _inst(sim, "sw2").is_root


def test_root_primary_fails_when_root_cannot_be_beaten(lab):
    sim, s = lab
    _config(s["sw1"], "spanning-tree vlan 1 priority 0")
    out = _config(s["sw2"], "spanning-tree vlan 1 root primary")
    assert any("Failed to make the bridge root" in o for o in out)
    assert _inst(sim, "sw1").is_root


def test_priority_change_reverts_the_tree(lab):
    sim, s = lab
    _config(s["sw2"], "spanning-tree vlan 1 priority 4096")
    assert _inst(sim, "sw2").is_root
    _config(s["sw2"], "spanning-tree vlan 1 priority 32768")
    assert _inst(sim, "sw1").is_root
    assert _role(sim, "sw2", "Fa0/2") == PortRole.ALTERNATE


def test_shutdown_root_port_fails_over(lab):
    sim, s = lab
    _config(s["sw2"], "shutdown", iface="FastEthernet0/1")
    assert _inst(sim, "sw2").root_port_name == "Fa0/2"
    _config(s["sw2"], "no shutdown", iface="FastEthernet0/1")
    assert _inst(sim, "sw2").root_port_name == "Fa0/1"


def test_port_cost_changes_root_port(lab):
    sim, s = lab
    _config(s["sw2"], "spanning-tree cost 100", iface="FastEthernet0/1")
    assert _inst(sim, "sw2").root_port_name == "Fa0/2"
    assert _role(sim, "sw2", "Fa0/1") == PortRole.ALTERNATE


def test_root_side_port_priority_changes_root_port(lab):
    """Equal cost: the neighbour's (sender's) port priority breaks the tie."""
    sim, s = lab
    _config(s["sw1"], "spanning-tree port-priority 64", iface="FastEthernet0/2")
    assert _inst(sim, "sw2").root_port_name == "Fa0/2"
    assert _role(sim, "sw2", "Fa0/1") == PortRole.ALTERNATE


def test_running_config_keeps_stp_settings(lab):
    _, s = lab
    _config(s["sw1"], "spanning-tree vlan 1 root secondary")
    _config(s["sw1"], "spanning-tree portfast", "spanning-tree cost 100",
            "spanning-tree port-priority 64", iface="FastEthernet0/3")
    run = s["sw1"].execute("show running-config")
    assert "spanning-tree mode " in run
    assert "spanning-tree vlan 1 priority 28672" in run
    block = run.split("interface FastEthernet0/3", 1)[1].split("!", 1)[0]
    assert " spanning-tree portfast" in block
    assert " spanning-tree port-priority 64" in block
    assert " spanning-tree cost 100" in block
    untouched = run.split("interface FastEthernet0/4", 1)[1].split("!", 1)[0]
    assert "spanning-tree" not in untouched


def test_summary_counts_only_up_ports(lab):
    _, s = lab
    out = s["sw2"].execute("show spanning-tree summary")
    row = next(l for l in out.splitlines() if l.startswith("VLAN0001")).split()
    blocking, forwarding, active = int(row[1]), int(row[4]), int(row[5])
    assert (blocking, forwarding, active) == (1, 1, 2)
    assert "1 vlan" in out
