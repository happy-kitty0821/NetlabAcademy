"""
VLAN lifecycle as on Catalyst IOS:

- ``no vlan N`` leaves ``switchport access vlan N`` on the ports; they go
  inactive (no traffic) and come back when VLAN N is created again.
- ``switchport access vlan N`` for a missing VLAN creates it.
- CDP logs ``%CDP-4-NATIVE_VLAN_MISMATCH`` when a link's ends disagree.

    PC1 Fa0/1 SW1 Fa0/23 ──── Fa0/23 SW2 Fa0/1 PC2
"""

from __future__ import annotations

import random
import re

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel, InterfaceState

_seed = iter(range(7000, 99999))


def _mac() -> MACAddress:
    return MACAddress.generate(random.Random(next(_seed)))


def _pc(dev_id: str, ip: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.HOST, hostname=dev_id.upper())
    d.add_interface(Interface(name="eth0", mac=_mac()))
    d.interfaces["eth0"].set_ip(ip)
    return d


def _switch(dev_id: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.SWITCH, hostname=dev_id.upper())
    d.supports_svi = True
    for i in range(1, 25):
        d.add_interface(Interface(name=f"Fa0/{i}", mac=_mac()))
    return d


@pytest.fixture()
def lab():
    topo = Topology()
    for d in (_pc("pc1", "192.168.20.11/24"), _pc("pc2", "192.168.20.12/24"),
              _switch("sw1"), _switch("sw2")):
        topo.add_device(d)
    for n, (a, ia, b, ib) in enumerate([("pc1", "eth0", "sw1", "Fa0/1"),
                                        ("pc2", "eth0", "sw2", "Fa0/1"),
                                        ("sw1", "Fa0/23", "sw2", "Fa0/23")]):
        topo.add_link(Link(id=f"l{n}", endpoint_a=(a, ia), endpoint_b=(b, ib)))
    sim = Simulation(topo, seed=5)
    s = {d: CLISession(device_id=d, simulation=sim) for d in ("sw1", "sw2", "pc1")}
    for sw in ("sw1", "sw2"):
        _cfg(s[sw], "vlan 20", "exit",
             "interface FastEthernet0/1", "switchport access vlan 20",
             "interface FastEthernet0/23", "switchport mode trunk")
    return sim, s


def _cfg(session: CLISession, *lines: str) -> list[str]:
    session.execute("enable")
    session.execute("configure terminal")
    out = [session.execute(line) for line in lines]
    session.execute("end")
    return out


def _ping(s) -> str:
    out = s["pc1"].execute("ping 192.168.20.12")
    return next(l for l in out.splitlines() if l and set(l) <= {"!", "."})


def _cdp_logs(sim, dev_id: str) -> list[str]:
    return [e.message for e in sim.syslog
            if e.device_id == dev_id and e.mnemonic == "NATIVE_VLAN_MISMATCH"]


# ── Deleting a VLAN ──────────────────────────────────────────────────────────

def test_deleted_vlan_keeps_port_config_and_goes_inactive(lab):
    sim, s = lab
    assert _ping(s) == "!!!!!"
    _cfg(s["sw2"], "no vlan 20")
    port = sim.topology.devices["sw2"].interfaces["Fa0/1"]
    assert port.vlan == 20                       # not moved to VLAN 1
    assert _ping(s) == "....."
    assert "Access Mode VLAN: 20 (Inactive)" in s["sw2"].execute("show interfaces fa0/1 switchport")
    status = next(l for l in s["sw2"].execute("show interfaces status").splitlines()
                  if l.startswith("Fa0/1 "))
    assert "inactive" in status
    assert " switchport access vlan 20" in s["sw2"].execute("show running-config interface fa0/1")
    assert not re.search(r"Fa0/1(?!\d)", s["sw2"].execute("show vlan brief"))


def test_recreating_the_vlan_reactivates_its_ports(lab):
    _, s = lab
    _cfg(s["sw2"], "no vlan 20")
    _cfg(s["sw2"], "vlan 20")
    assert _ping(s) == "!!!!!"


def test_inactive_port_does_not_join_vlan_1(lab):
    """The old behaviour moved the port into VLAN 1; it must stay isolated."""
    sim, s = lab
    _cfg(s["sw2"], "no vlan 20")
    _cfg(s["sw1"], "interface FastEthernet0/1", "switchport access vlan 1")
    assert _ping(s) == "....."                    # PC2's port is inactive, not VLAN 1


def test_svi_goes_down_with_its_vlan(lab):
    sim, s = lab
    _cfg(s["sw2"], "interface vlan 20", "ip address 192.168.20.2 255.255.255.0", "no shutdown")
    svi = sim.topology.devices["sw2"].interfaces["Vlan20"]
    assert svi.oper_state == InterfaceState.UP
    _cfg(s["sw2"], "no vlan 20")
    assert svi.oper_state == InterfaceState.DOWN


# ── switchport access vlan <missing> ─────────────────────────────────────────

def test_access_vlan_creates_a_missing_vlan(lab):
    sim, s = lab
    out = _cfg(s["sw1"], "interface FastEthernet0/5", "switchport access vlan 30")
    assert out[-1] == "% Access VLAN does not exist. Creating vlan 30"
    assert 30 in sim.get_switch("sw1").vlans
    assert sim.topology.devices["sw1"].interfaces["Fa0/5"].vlan == 30
    assert "VLAN0030" in s["sw1"].execute("show vlan brief")
    # Existing VLAN: no message
    assert _cfg(s["sw1"], "interface FastEthernet0/6", "switchport access vlan 30")[-1] == ""


def test_access_vlan_out_of_range_is_rejected(lab):
    _, s = lab
    out = _cfg(s["sw1"], "interface FastEthernet0/5", "switchport access vlan 4095")
    assert "Invalid input" in out[-1]


# ── CDP native VLAN mismatch ─────────────────────────────────────────────────

def test_native_vlan_mismatch_is_logged_on_both_switches(lab):
    sim, s = lab
    assert _cdp_logs(sim, "sw1") == []
    _cfg(s["sw1"], "interface FastEthernet0/23", "switchport trunk native vlan 20")
    assert _cdp_logs(sim, "sw1") == [
        "Native VLAN mismatch discovered on FastEthernet0/23 (20), with SW2 FastEthernet0/23 (1)."]
    assert _cdp_logs(sim, "sw2") == [
        "Native VLAN mismatch discovered on FastEthernet0/23 (1), with SW1 FastEthernet0/23 (20)."]
    # Further commands while it lasts do not repeat it
    _cfg(s["sw1"], "interface FastEthernet0/5", "description spare")
    assert len(_cdp_logs(sim, "sw1")) == 1


def test_fixing_the_native_vlan_clears_the_mismatch(lab):
    sim, s = lab
    _cfg(s["sw1"], "interface FastEthernet0/23", "switchport trunk native vlan 20")
    _cfg(s["sw2"], "interface FastEthernet0/23", "switchport trunk native vlan 20")
    assert len(_cdp_logs(sim, "sw1")) == 1
    _cfg(s["sw2"], "interface FastEthernet0/23", "switchport trunk native vlan 1")
    assert len(_cdp_logs(sim, "sw1")) == 2       # a new mismatch is a new message


def test_trunk_facing_access_port_in_other_vlan_mismatches(lab):
    sim, s = lab
    _cfg(s["sw2"], "interface FastEthernet0/23", "switchport mode access", "switchport access vlan 20")
    assert "(1), with SW2 FastEthernet0/23 (20)." in _cdp_logs(sim, "sw1")[0]


def test_no_cdp_run_suppresses_the_message(lab):
    sim, s = lab
    _cfg(s["sw1"], "no cdp run")
    _cfg(s["sw1"], "interface FastEthernet0/23", "switchport trunk native vlan 20")
    assert _cdp_logs(sim, "sw1") == [] and _cdp_logs(sim, "sw2") == []
