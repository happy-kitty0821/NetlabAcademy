"""
Spanning-tree protections: root guard, loop guard, BPDU filter, PortFast
behaviour and the global defaults.

Triangle (SW1 is the root):

    SW1 Fa0/1 ──── Fa0/1 SW2
    SW1 Fa0/2 ──── Fa0/1 SW3
    SW2 Fa0/2 ──── Fa0/2 SW3        SW3 Fa0/2 is the alternate (blocked) port
    PC1 on SW1 Fa0/10, PC3 on SW3 Fa0/10
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.l2.stp import PortRole, PortState
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel

_seed = iter(range(11000, 99999))


def _mac() -> MACAddress:
    return MACAddress.generate(random.Random(next(_seed)))


def _switch(dev_id: str) -> Device:
    # Fixed MACs (SW1 < SW2 < SW3) so the tree is the same in every test:
    # SW2 Fa0/2 is designated, SW3 Fa0/2 the alternate.
    base = int(dev_id[-1])
    d = Device(id=dev_id, model=DeviceModel.SWITCH, hostname=dev_id.upper())
    for i in range(1, 25):
        d.add_interface(Interface(name=f"Fa0/{i}", mac=MACAddress(f"aa:00:00:00:{base:02x}:{i:02x}")))
    return d


def _pc(dev_id: str, ip: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.HOST, hostname=dev_id.upper())
    d.add_interface(Interface(name="eth0", mac=_mac()))
    d.interfaces["eth0"].set_ip(ip)
    return d


@pytest.fixture()
def lab():
    topo = Topology()
    for d in (_switch("sw1"), _switch("sw2"), _switch("sw3"),
              _pc("pc1", "10.0.0.1/24"), _pc("pc3", "10.0.0.3/24")):
        topo.add_device(d)
    for n, (a, ia, b, ib) in enumerate([("sw1", "Fa0/1", "sw2", "Fa0/1"),
                                        ("sw1", "Fa0/2", "sw3", "Fa0/1"),
                                        ("sw2", "Fa0/2", "sw3", "Fa0/2"),
                                        ("pc1", "eth0", "sw1", "Fa0/10"),
                                        ("pc3", "eth0", "sw3", "Fa0/10")]):
        topo.add_link(Link(id=f"l{n}", endpoint_a=(a, ia), endpoint_b=(b, ib)))
    sim = Simulation(topo, seed=9)
    s = {d: CLISession(device_id=d, simulation=sim) for d in ("sw1", "sw2", "sw3", "pc1")}
    for x in ("sw1", "sw2", "sw3"):
        s[x].execute("enable")
    _cfg(s["sw1"], "spanning-tree vlan 1 priority 4096")
    return sim, s


def _cfg(session: CLISession, *lines: str, iface: str | None = None) -> list[str]:
    session.execute("configure terminal")
    if iface:
        session.execute(f"interface {iface}")
    out = [session.execute(line) for line in lines]
    session.execute("end")
    return out


def _port(sim, dev: str, name: str):
    return sim.get_switch(dev).stp.get_instance(1).port_states[name]


def _row(s, dev: str, name: str) -> str:
    return next(l for l in s[dev].execute("show spanning-tree vlan 1").splitlines()
                if l.startswith(name + " "))


def _ping(s) -> str:
    out = s["pc1"].execute("ping 10.0.0.3")
    return next(l for l in out.splitlines() if l and set(l) <= {"!", "."})


def _logs(sim, mnemonic: str) -> list[str]:
    return [e.message for e in sim.syslog if e.mnemonic == mnemonic]


def test_baseline_tree(lab):
    sim, s = lab
    assert sim.get_switch("sw1").stp.get_instance(1).is_root
    assert _port(sim, "sw3", "Fa0/2").role == PortRole.ALTERNATE
    assert _ping(s) == "!!!!!"


# ── root guard ────────────────────────────────────────────────────────────────

def test_root_guard_blocks_a_rogue_root(lab):
    sim, s = lab
    _cfg(s["sw2"], "spanning-tree guard root", iface="FastEthernet0/2")
    _cfg(s["sw3"], "spanning-tree vlan 1 priority 0")
    port = _port(sim, "sw2", "Fa0/2")
    assert port.state == PortState.ROOT_INCONSISTENT
    assert not sim.get_switch("sw2").stp.get_instance(1).is_root
    assert sim.get_switch("sw2").stp.get_instance(1).root_port_name == "Fa0/1"
    assert _row(s, "sw2", "Fa0/2").split() == ["Fa0/2", "Desg", "BKN*19", "128.2", "P2p", "*ROOT_Inc"]
    assert _logs(sim, "ROOTGUARD_BLOCK") == ["Root guard blocking port FastEthernet0/2 on VLAN0001."]
    out = s["sw2"].execute("show spanning-tree inconsistentports")
    assert "VLAN0001             FastEthernet0/2          Root Inconsistent" in out
    assert out.endswith("Number of inconsistent ports (segments) in the system : 1")
    # The rogue backs off: the port recovers on its own.
    _cfg(s["sw3"], "spanning-tree vlan 1 priority 32768")
    assert _port(sim, "sw2", "Fa0/2").state == PortState.FORWARDING
    assert _logs(sim, "ROOTGUARD_UNBLOCK") == ["Root guard unblocking port FastEthernet0/2 on VLAN0001."]


def test_root_guard_on_the_root_port_is_inconsistent(lab):
    """Root guard where the root actually is: that port can never be the root port."""
    sim, s = lab
    _cfg(s["sw3"], "spanning-tree guard root", iface="FastEthernet0/1")
    assert _port(sim, "sw3", "Fa0/1").state == PortState.ROOT_INCONSISTENT
    assert sim.get_switch("sw3").stp.get_instance(1).root_port_name == "Fa0/2"
    assert _ping(s) == "!!!!!"


# ── BPDU filter and loop guard ────────────────────────────────────────────────

def test_bpdu_filter_on_a_redundant_link_makes_a_loop(lab):
    sim, s = lab
    _cfg(s["sw2"], "spanning-tree bpdufilter enable", iface="FastEthernet0/2")
    # SW3 stops hearing BPDUs on its blocked port and starts forwarding.
    assert _port(sim, "sw3", "Fa0/2").state == PortState.FORWARDING
    assert _ping(s) == "....."
    assert _logs(sim, "MACFLAP_NOTIF"), "a loop makes MAC addresses flap"


def test_loop_guard_keeps_the_port_blocked(lab):
    sim, s = lab
    _cfg(s["sw3"], "spanning-tree guard loop", iface="FastEthernet0/2")
    _cfg(s["sw2"], "spanning-tree bpdufilter enable", iface="FastEthernet0/2")
    port = _port(sim, "sw3", "Fa0/2")
    assert port.state == PortState.LOOP_INCONSISTENT and port.is_blocking
    assert "*LOOP_Inc" in _row(s, "sw3", "Fa0/2")
    assert _logs(sim, "LOOPGUARD_BLOCK") == ["Loop guard blocking port FastEthernet0/2 on VLAN0001."]
    assert _ping(s) == "!!!!!"
    _cfg(s["sw2"], "no spanning-tree bpdufilter enable", iface="FastEthernet0/2")
    assert _port(sim, "sw3", "Fa0/2").role == PortRole.ALTERNATE
    assert _logs(sim, "LOOPGUARD_UNBLOCK") == ["Loop guard unblocking port FastEthernet0/2 on VLAN0001."]


def test_loop_guard_default(lab):
    sim, s = lab
    _cfg(s["sw3"], "spanning-tree loopguard default")
    _cfg(s["sw2"], "spanning-tree bpdufilter enable", iface="FastEthernet0/2")
    assert _port(sim, "sw3", "Fa0/2").state == PortState.LOOP_INCONSISTENT
    _cfg(s["sw3"], "no spanning-tree loopguard default")
    assert _port(sim, "sw3", "Fa0/2").state == PortState.FORWARDING


def test_loop_guard_on_a_designated_port_does_nothing(lab):
    sim, s = lab
    _cfg(s["sw2"], "spanning-tree guard loop", iface="FastEthernet0/2")
    _cfg(s["sw3"], "spanning-tree bpdufilter enable", iface="FastEthernet0/2")
    assert _port(sim, "sw2", "Fa0/2").state == PortState.FORWARDING


# ── PortFast and the defaults ─────────────────────────────────────────────────

def test_portfast_on_a_switch_link_is_not_an_edge(lab):
    """A PortFast port that hears BPDUs loses edge status and can still block."""
    sim, s = lab
    _cfg(s["sw3"], "spanning-tree portfast", iface="FastEthernet0/2")
    port = _port(sim, "sw3", "Fa0/2")
    assert port.role == PortRole.ALTERNATE and port.is_blocking
    assert "Edge" not in _row(s, "sw3", "Fa0/2")
    _cfg(s["sw3"], "spanning-tree portfast", iface="FastEthernet0/10")
    assert _row(s, "sw3", "Fa0/10").endswith("P2p Edge")


def test_portfast_and_bpduguard_defaults(lab):
    sim, s = lab
    _cfg(s["sw2"], "interface Fa0/1", "switchport mode trunk")
    out = _cfg(s["sw2"], "spanning-tree portfast default", "spanning-tree portfast bpduguard default")
    assert out[0].startswith("%Warning: this command enables portfast by default")
    ports = sim.topology.devices["sw2"].interfaces
    assert ports["Fa0/2"].err_disabled == "bpduguard"      # access port facing SW3
    assert ports["Fa0/1"].err_disabled is None             # trunks are not PortFast by default
    run = s["sw2"].execute("show running-config")
    assert "spanning-tree portfast default" in run
    assert "spanning-tree portfast bpduguard default" in run
    summary = s["sw2"].execute("show spanning-tree summary")
    assert "Portfast Default             is enabled" in summary
    assert "PortFast BPDU Guard Default  is enabled" in summary
    assert "Loopguard Default            is disabled" in summary


def test_bpdufilter_default_and_no_forms(lab):
    sim, s = lab
    _cfg(s["sw1"], "spanning-tree portfast bpdufilter default")
    assert "Portfast BPDU Filter Default is enabled" in s["sw1"].execute("show spanning-tree summary")
    assert "spanning-tree portfast bpdufilter default" in s["sw1"].execute("show running-config")
    _cfg(s["sw1"], "no spanning-tree portfast bpdufilter default")
    assert "spanning-tree portfast bpdufilter" not in s["sw1"].execute("show running-config")


# ── show spanning-tree detail ─────────────────────────────────────────────────

def test_show_spanning_tree_detail(lab):
    sim, s = lab
    _cfg(s["sw3"], "spanning-tree guard root", iface="FastEthernet0/10")
    out = s["sw3"].execute("show spanning-tree detail")
    assert out.startswith(" VLAN0001 is executing the rstp compatible Spanning Tree protocol")
    assert "  Root port is 1 (FastEthernet0/1), cost of root path is 19" in out
    blocked = out.split(" Port 2 (FastEthernet0/2) of VLAN0001 is ")[1]
    assert blocked.startswith("alternate blocking")
    edge = out.split(" Port 10 (FastEthernet0/10) of VLAN0001 is ")[1]
    assert "Root guard is enabled on the port" in edge
    root_out = s["sw1"].execute("show spanning-tree detail")
    assert "  We are the root of the spanning tree" in root_out
