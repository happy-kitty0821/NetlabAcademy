"""
DTP: dynamic auto / dynamic desirable ports negotiate a trunk with their
neighbour, following the IOS mode matrix.

Lab:

    PC1 (VLAN 10) ─ Fa0/1 SW1 Fa0/23 ──── Fa0/23 SW2 Fa0/1 ─ PC3 (VLAN 10)
                          SW1 Fa0/22 ──── Fa0/22 SW2
                          SW1 Fa0/20 ──── Gi0/0 R1
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.simulation import Simulation
from simulator_core.stp import PortRole
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel

_seed = iter(range(5000, 100000))


def _mac() -> MACAddress:
    return MACAddress.generate(random.Random(next(_seed)))


def _pc(dev_id: str, ip: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.HOST, hostname=dev_id.upper())
    d.add_interface(Interface(name="eth0", mac=_mac()))
    d.interfaces["eth0"].set_ip(ip)
    return d


def _switch(dev_id: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.SWITCH, hostname=dev_id.upper())
    for i in range(24):
        d.add_interface(Interface(name=f"Fa0/{i}", mac=_mac()))
    return d


def _router(dev_id: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.ROUTER, hostname=dev_id.upper())
    for i in range(2):
        d.add_interface(Interface(name=f"Gi0/{i}", mac=_mac()))
    return d


@pytest.fixture()
def lab():
    topo = Topology()
    for d in (_pc("pc1", "192.168.10.11/24"), _pc("pc3", "192.168.10.13/24"),
              _switch("sw1"), _switch("sw2"), _router("r1")):
        topo.add_device(d)
    links = [("pc1", "eth0", "sw1", "Fa0/1"), ("pc3", "eth0", "sw2", "Fa0/1"),
             ("sw1", "Fa0/23", "sw2", "Fa0/23"), ("sw1", "Fa0/20", "r1", "Gi0/0")]
    for n, (a, ia, b, ib) in enumerate(links):
        topo.add_link(Link(id=f"l{n}", endpoint_a=(a, ia), endpoint_b=(b, ib)))
    sim = Simulation(topo, seed=7)
    sessions = {}
    for dev in ("sw1", "sw2", "pc1"):
        s = CLISession(device_id=dev, simulation=sim)
        s.execute("enable")
        sessions[dev] = s
    for dev in ("sw1", "sw2"):
        _config(sessions[dev], "vlan 10")
        _config(sessions[dev], "switchport access vlan 10", iface="FastEthernet0/1")
    return sim, sessions


def _config(session: CLISession, *lines: str, iface: str | None = None) -> list[str]:
    out = [session.execute("configure terminal")]
    if iface:
        out.append(session.execute(f"interface {iface}"))
    out += [session.execute(line) for line in lines]
    session.execute("end")
    return out


def _mode_cmd(mode: str) -> list[str]:
    """Interface commands for a test mode name."""
    return {
        "auto": ["switchport mode dynamic auto"],
        "desirable": ["switchport mode dynamic desirable"],
        "trunk": ["switchport mode trunk"],
        "access": ["switchport mode access"],
        "nonegotiate": ["switchport mode trunk", "switchport nonegotiate"],
    }[mode]


def _set(s, dev, mode, port="FastEthernet0/23"):
    out = _config(s[dev], *_mode_cmd(mode), iface=port)
    assert not any(o.startswith(("%", "Command rejected")) for o in out), out


def _iface(sim, dev, port="Fa0/23"):
    return sim.topology.devices[dev].interfaces[port]


def _ping(s, target: str) -> str:
    out = s["pc1"].execute(f"ping {target}")
    return next(l for l in out.strip().splitlines() if l and set(l) <= {"!", "."})


# (SW1 mode, SW2 mode) -> does the link trunk?
MATRIX = [
    ("auto", "auto", False),
    ("auto", "desirable", True),
    ("auto", "trunk", True),
    ("auto", "access", False),
    ("auto", "nonegotiate", False),
    ("desirable", "desirable", True),
    ("desirable", "trunk", True),
    ("desirable", "access", False),
    ("desirable", "nonegotiate", False),
]


@pytest.mark.parametrize("mode1, mode2, trunks", MATRIX)
def test_dtp_matrix(lab, mode1, mode2, trunks):
    sim, s = lab
    _set(s, "sw1", mode1)
    _set(s, "sw2", mode2)
    assert _iface(sim, "sw1").is_trunk is trunks
    if mode2 in ("auto", "desirable"):
        assert _iface(sim, "sw2").is_trunk is trunks
    show = s["sw1"].execute("show interfaces fa0/23 switchport")
    assert f"Operational Mode: {'trunk' if trunks else 'static access'}" in show


def test_negotiated_trunk_carries_vlan_traffic(lab):
    sim, s = lab
    assert _ping(s, "192.168.10.13") == "....."      # access link in VLAN 1
    _set(s, "sw1", "desirable")
    _set(s, "sw2", "auto")
    assert _ping(s, "192.168.10.13") == "!!!!!"


def test_show_interfaces_trunk_lists_negotiated_ports(lab):
    _, s = lab
    _set(s, "sw1", "desirable")
    assert "Fa0/23" not in s["sw1"].execute("show interfaces trunk")
    _set(s, "sw2", "auto")
    out1 = s["sw1"].execute("show interfaces trunk")
    out2 = s["sw2"].execute("show interfaces trunk")
    row1 = next(l for l in out1.splitlines() if l.startswith("Fa0/23")).split()
    row2 = next(l for l in out2.splitlines() if l.startswith("Fa0/23")).split()
    assert row1[1:4] == ["desirable", "dot1q", "trunking"]
    assert row2[1:4] == ["auto", "dot1q", "trunking"]


def test_show_switchport_admin_and_oper_modes(lab):
    _, s = lab
    _set(s, "sw1", "auto")
    out = s["sw1"].execute("show interfaces fa0/23 switchport")
    assert "Administrative Mode: dynamic auto" in out
    assert "Operational Mode: static access" in out
    assert "Negotiation of Trunking: On" in out
    _set(s, "sw2", "desirable")
    out = s["sw1"].execute("show interfaces fa0/23 switchport")
    assert "Operational Mode: trunk" in out
    assert "Operational Trunking Encapsulation: dot1q" in out
    _set(s, "sw2", "nonegotiate")
    out = s["sw2"].execute("show interfaces fa0/23 switchport")
    assert "Administrative Mode: trunk" in out
    assert "Negotiation of Trunking: Off" in out


def test_trunk_drops_when_peer_changes_or_link_goes_down(lab):
    sim, s = lab
    _set(s, "sw1", "desirable")
    _set(s, "sw2", "auto")
    assert _iface(sim, "sw2").is_trunk
    _set(s, "sw1", "access")
    assert not _iface(sim, "sw2").is_trunk
    _set(s, "sw1", "trunk")
    assert _iface(sim, "sw2").is_trunk
    _config(s["sw1"], "shutdown", iface="FastEthernet0/23")
    assert not _iface(sim, "sw2").is_trunk
    _config(s["sw1"], "no shutdown", iface="FastEthernet0/23")
    assert _iface(sim, "sw2").is_trunk


def test_negotiated_access_port_uses_access_vlan(lab):
    """An untrunked dynamic port runs in its access VLAN and shows in show vlan."""
    sim, s = lab
    _set(s, "sw1", "auto")
    _set(s, "sw2", "auto")
    for dev in ("sw1", "sw2"):
        _config(s[dev], "switchport access vlan 10", iface="FastEthernet0/23")
    assert _ping(s, "192.168.10.13") == "!!!!!"
    vlan = s["sw1"].execute("show vlan brief")
    vlan10 = next(l for l in vlan.splitlines() if l.startswith("10 "))
    assert "Fa0/23" in vlan10
    status = s["sw1"].execute("show interfaces status")
    row = next(l for l in status.splitlines() if l.startswith("Fa0/23")).split()
    assert "10" in row


def test_dynamic_port_to_router_stays_access(lab):
    sim, s = lab
    _set(s, "sw1", "desirable", port="FastEthernet0/20")
    assert not _iface(sim, "sw1", "Fa0/20").is_trunk


def test_nonegotiate_conflicts_with_dynamic(lab):
    sim, s = lab
    out = _config(s["sw1"], "switchport mode dynamic desirable", "switchport nonegotiate",
                  iface="FastEthernet0/23")
    assert "Command rejected: Conflict between 'nonegotiate' and 'dynamic' status." in out
    assert not _iface(sim, "sw1").dtp_nonegotiate

    out = _config(s["sw2"], "switchport mode trunk", "switchport nonegotiate",
                  "switchport mode dynamic auto", iface="FastEthernet0/23")
    assert out[-1] == "Command rejected: Conflict between 'nonegotiate' and 'dynamic' status."
    assert _iface(sim, "sw2").switchport_mode == "trunk"
    assert not _iface(sim, "sw1").is_trunk           # SW2 sends no DTP

    _config(s["sw2"], "no switchport nonegotiate", iface="FastEthernet0/23")
    assert not _iface(sim, "sw2").dtp_nonegotiate
    assert _iface(sim, "sw1").is_trunk


def test_running_config_shows_dtp_settings(lab):
    _, s = lab
    _set(s, "sw1", "desirable")
    _set(s, "sw2", "nonegotiate")
    run1 = s["sw1"].execute("show running-config interface FastEthernet0/23")
    run2 = s["sw2"].execute("show running-config interface FastEthernet0/23")
    assert " switchport mode dynamic desirable" in run1
    assert run2.index(" switchport mode trunk") < run2.index(" switchport nonegotiate")


def test_negotiated_trunks_form_per_vlan_spanning_tree(lab):
    """Two negotiated trunks make a VLAN 10 loop, so one port must block."""
    sim, s = lab
    sim.add_link(Link(id="l9", endpoint_a=("sw1", "Fa0/22"), endpoint_b=("sw2", "Fa0/22")))
    sim.refresh_interface_states()
    for port in ("FastEthernet0/22", "FastEthernet0/23"):
        _set(s, "sw1", "desirable", port=port)
        _set(s, "sw2", "auto", port=port)
    states = [sim.get_switch(d).stp.get_instance(10).port_states for d in ("sw1", "sw2")]
    alternates = [n for st in states for n, p in st.items()
                  if n in ("Fa0/22", "Fa0/23") and p.role == PortRole.ALTERNATE]
    assert len(alternates) == 1


def test_no_switchport_settings_reset_only_that_setting(lab):
    sim, s = lab
    _config(s["sw1"], "switchport mode dynamic desirable", "switchport access vlan 10",
            "switchport trunk native vlan 10", "switchport trunk allowed vlan 1,10",
            iface="FastEthernet0/23")
    _config(s["sw1"], "no switchport access vlan", "no switchport trunk native vlan",
            "no switchport trunk allowed vlan", iface="FastEthernet0/23")
    iface = _iface(sim, "sw1")
    assert iface.switchport_mode == "dynamic_desirable"
    assert (iface.vlan, iface.trunk_native_vlan, iface.trunk_allowed_vlans) == (1, 1, None)
