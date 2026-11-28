"""
EtherChannel between two Catalyst switches.

    PC1 eth0 ── Fa0/1 SW1 Fa0/23 ──── Fa0/23 SW2 Fa0/1 ── eth0 PC2
                      SW1 Fa0/24 ──── Fa0/24 SW2
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

_seed = iter(range(8000, 99999))


def _mac() -> MACAddress:
    return MACAddress.generate(random.Random(next(_seed)))


def _pc(dev_id: str, ip: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.HOST, hostname=dev_id.upper())
    d.add_interface(Interface(name="eth0", mac=_mac()))
    d.interfaces["eth0"].set_ip(ip)
    return d


def _switch(dev_id: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.SWITCH, hostname=dev_id.upper())
    for i in range(1, 25):
        d.add_interface(Interface(name=f"Fa0/{i}", mac=_mac()))
    return d


@pytest.fixture()
def lab():
    topo = Topology()
    for d in (_pc("pc1", "10.0.0.1/24"), _pc("pc2", "10.0.0.2/24"), _switch("sw1"), _switch("sw2")):
        topo.add_device(d)
    for n, (a, ia, b, ib) in enumerate([("pc1", "eth0", "sw1", "Fa0/1"),
                                        ("pc2", "eth0", "sw2", "Fa0/1"),
                                        ("sw1", "Fa0/23", "sw2", "Fa0/23"),
                                        ("sw1", "Fa0/24", "sw2", "Fa0/24")]):
        topo.add_link(Link(id=f"l{n}", endpoint_a=(a, ia), endpoint_b=(b, ib)))
    sim = Simulation(topo, seed=6)
    s = {d: CLISession(device_id=d, simulation=sim) for d in ("sw1", "sw2", "pc1")}
    for x in ("sw1", "sw2"):
        s[x].execute("enable")
    return sim, s


def _cfg(session: CLISession, *lines: str) -> list[str]:
    session.execute("configure terminal")
    out = [session.execute(line) for line in lines]
    session.execute("end")
    return out


def _bundle(s, dev: str, mode: str, *extra: str) -> list[str]:
    return _cfg(s[dev], "interface range Fa0/23 - 24", f"channel-group 1 mode {mode}", *extra)


def _states(sim, dev: str) -> dict[str, str]:
    pc = sim.get_switch(dev).port_channels[1]
    return {m: pc.member_flag(m) for m in pc.members}


def _po(sim, dev: str, name: str = "Po1"):
    return sim.topology.devices[dev].interfaces[name]


def _ping(s) -> str:
    out = s["pc1"].execute("ping 10.0.0.2")
    return next(l for l in out.splitlines() if l and set(l) <= {"!", "."})


def _logs(sim, mnemonic: str) -> list[str]:
    return [e.message for e in sim.syslog if e.mnemonic == mnemonic]


# ── negotiation ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode1, mode2, bundled", [
    ("active", "active", True), ("active", "passive", True), ("passive", "passive", False),
    ("desirable", "desirable", True), ("desirable", "auto", True), ("auto", "auto", False),
    ("on", "on", True),
])
def test_negotiation_matrix(lab, mode1, mode2, bundled):
    sim, s = lab
    if mode1 == "on":
        # Best practice for static channels: configure "on" with the ports
        # shut, or the far switch's BPDUs trip the EtherChannel guard
        # (see test_on_facing_individual_ports_is_err_disabled).
        _cfg(s["sw1"], "interface range Fa0/23 - 24", "shutdown")
    _bundle(s, "sw1", mode1)
    _bundle(s, "sw2", mode2)
    if mode1 == "on":
        _cfg(s["sw1"], "interface range Fa0/23 - 24", "no shutdown")
    want = "P" if bundled else "I"
    assert _states(sim, "sw1") == {"Fa0/23": want, "Fa0/24": want}
    assert (_po(sim, "sw1").oper_state == InterfaceState.UP) is bundled
    assert _ping(s) == "!!!!!"            # bundled or not, the switches stay connected


def test_lacp_with_a_non_channel_neighbour_stays_stand_alone(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    assert _states(sim, "sw1") == {"Fa0/23": "I", "Fa0/24": "I"}


def test_creation_message_and_bundle_logs(lab):
    sim, s = lab
    out = _bundle(s, "sw1", "active")
    assert out[1] == "Creating a port-channel interface Port-channel 1"
    _bundle(s, "sw2", "active")
    assert "Interface Fa0/23 joined port-channel Po1" in _logs(sim, "BUNDLE")
    texts = [f"%{e.facility}-{e.severity}-{e.mnemonic}: {e.message}" for e in sim.syslog
             if e.device_id == "sw1"]
    assert "%LINK-3-UPDOWN: Interface Port-channel1, changed state to up" in texts


# ── the bundle is one port ────────────────────────────────────────────────────

def test_spanning_tree_sees_one_port_with_bundle_cost(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "active")
    out = s["sw2"].execute("show spanning-tree vlan 1")
    ports = [l.split()[0] for l in out.splitlines() if re.match(r"^(Fa|Po)\S+\s+(Root|Desg|Altn)", l)]
    assert "Po1" in ports and "Fa0/23" not in ports and "Fa0/24" not in ports
    po_row = next(l for l in out.splitlines() if l.startswith("Po1"))
    assert po_row.split()[3] == "12"                   # 2 x 100 Mb/s
    # Nothing is blocked: the two cables are one link.
    assert "Altn" not in out


def test_traffic_and_mac_learning_use_the_port_channel(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "active")
    assert _ping(s) == "!!!!!"
    assert "Po1" in sim.get_switch("sw1").mac_table.values()
    assert not {"Fa0/23", "Fa0/24"} & set(sim.get_switch("sw1").mac_table.values())


def test_losing_one_member_keeps_the_bundle_up(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "active")
    _cfg(s["sw1"], "interface Fa0/24", "shutdown")
    assert _states(sim, "sw1") == {"Fa0/23": "P", "Fa0/24": "D"}
    assert _po(sim, "sw1").oper_state == InterfaceState.UP
    assert sim.get_switch("sw1").stp.get_instance(1).port_states["Po1"].path_cost == 19
    assert _ping(s) == "!!!!!"


def test_shutting_the_port_channel_takes_the_bundle_down(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "active")
    _cfg(s["sw1"], "interface port-channel 1", "shutdown")
    assert _states(sim, "sw1") == {"Fa0/23": "D", "Fa0/24": "D"}
    assert _po(sim, "sw1").oper_state == InterfaceState.DOWN


# ── configuration ─────────────────────────────────────────────────────────────

def test_port_channel_config_reaches_members(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _cfg(s["sw1"], "vlan 10", "exit", "interface po1", "switchport mode trunk",
         "switchport trunk allowed vlan 1,10")
    for m in ("Fa0/23", "Fa0/24"):
        port = sim.topology.devices["sw1"].interfaces[m]
        assert port.switchport_mode == "trunk" and port.trunk_allowed_vlans == [1, 10]
    # A new member takes on the port-channel's configuration.
    _cfg(s["sw1"], "interface Fa0/22", "channel-group 1 mode active")
    assert sim.topology.devices["sw1"].interfaces["Fa0/22"].switchport_mode == "trunk"


def test_member_with_different_config_is_suspended(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "active")
    _cfg(s["sw1"], "vlan 99", "exit", "interface Fa0/24", "switchport access vlan 99")
    assert _states(sim, "sw1") == {"Fa0/23": "P", "Fa0/24": "s"}
    assert _logs(sim, "CANNOT_BUNDLE2") == [
        "Fa0/24 is not compatible with Po1 and will be suspended (access vlan of Fa0/24 is 99, Po1 id 1)"]
    row = next(l for l in s["sw1"].execute("show interfaces status").splitlines() if l.startswith("Fa0/24"))
    assert "suspended" in row
    _cfg(s["sw1"], "interface Fa0/24", "switchport access vlan 1")
    assert _states(sim, "sw1") == {"Fa0/23": "P", "Fa0/24": "P"}


def test_protocol_mismatch_and_invalid_group_are_rejected(lab):
    _, s = lab
    _cfg(s["sw1"], "interface Fa0/23", "channel-group 1 mode active")
    out = _cfg(s["sw1"], "interface Fa0/24", "channel-group 1 mode desirable")
    assert out[1] == ("Command rejected (Channel protocol mismatch for interface Fa0/24 in group 1): "
                      "the interface can not be added to the channel group")
    assert "Invalid input" in _cfg(s["sw1"], "interface Fa0/24", "channel-group 7 mode on")[1]
    assert _cfg(s["sw1"], "interface port-channel 7")[0].startswith("% Invalid interface name")


def test_on_facing_individual_ports_is_err_disabled(lab):
    sim, s = lab
    _bundle(s, "sw1", "on")
    ports = sim.topology.devices["sw1"].interfaces
    assert ports["Fa0/23"].err_disabled == ports["Fa0/24"].err_disabled == "channel-misconfig"
    assert _logs(sim, "CHNL_MISCFG") == [
        "Detected loop due to etherchannel misconfiguration of Po1 Fa0/23 Fa0/24"]
    assert "channel-misconfig (STP) error detected on Po1, putting Fa0/23 in err-disable state" in \
        _logs(sim, "ERR_DISABLE")


def test_removing_members_and_the_port_channel(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _cfg(s["sw1"], "interface Fa0/24", "no channel-group")
    assert sim.get_switch("sw1").port_channels[1].members == ["Fa0/23"]
    assert sim.topology.devices["sw1"].interfaces["Fa0/24"].channel_group is None
    _cfg(s["sw1"], "no interface port-channel 1")
    assert 1 not in sim.get_switch("sw1").port_channels
    assert "Po1" not in sim.topology.devices["sw1"].interfaces
    assert sim.topology.devices["sw1"].interfaces["Fa0/23"].channel_group is None


def test_running_config(lab):
    _, s = lab
    _bundle(s, "sw1", "active")
    _cfg(s["sw1"], "interface po1", "switchport mode trunk", "exit", "port-channel load-balance src-dst-mac")
    run = s["sw1"].execute("show running-config")
    assert run.index("interface Port-channel1") < run.index("interface FastEthernet0/1")
    block = run.split("interface FastEthernet0/23", 1)[1].split("!", 1)[0]
    assert " switchport mode trunk" in block and " channel-group 1 mode active" in block
    assert "port-channel load-balance src-dst-mac" in run


# ── show commands ─────────────────────────────────────────────────────────────

def test_show_etherchannel_summary(lab):
    _, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "active")
    out = s["sw1"].execute("show etherchannel summary")
    assert "Number of channel-groups in use: 1" in out
    row = next(l for l in out.splitlines() if l.startswith("1 "))
    assert row.split() == ["1", "Po1(SU)", "LACP", "Fa0/23(P)", "Fa0/24(P)"]


def test_show_lacp_and_pagp_neighbors(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "passive")
    rows = [l for l in s["sw1"].execute("show lacp neighbor").splitlines() if l.startswith("Fa0/2")]
    assert [r.split()[:2] for r in rows] == [["Fa0/23", "SP"], ["Fa0/24", "SP"]]
    _cfg(s["sw1"], "no interface port-channel 1")
    _cfg(s["sw2"], "no interface port-channel 1")
    _bundle(s, "sw1", "desirable")
    _bundle(s, "sw2", "desirable")
    rows = [l for l in s["sw1"].execute("show pagp neighbor").splitlines() if l.startswith("Fa0/2")]
    assert [r.split()[:2] for r in rows] == [["Fa0/23", "SW2"], ["Fa0/24", "SW2"]]


def test_trunk_and_vlan_listings_show_the_port_channel(lab):
    _, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "active")
    vlan1 = s["sw1"].execute("show vlan brief").split("1002 ")[0]
    assert "Po1" in vlan1 and "Fa0/23" not in vlan1
    _cfg(s["sw1"], "interface po1", "switchport mode trunk")
    trunk = s["sw1"].execute("show interfaces trunk")
    assert "Po1" in trunk and "Fa0/23" not in trunk


def test_load_balance_spreads_flows(lab):
    sim, s = lab
    _bundle(s, "sw1", "active")
    _bundle(s, "sw2", "active")
    _cfg(s["sw1"], "port-channel load-balance src-dst-mac")
    out = s["sw1"].execute("show etherchannel load-balance")
    assert "src-dst-mac" in out and "Non-IP: Source XOR Destination MAC address" in out
    pc = sim.get_switch("sw1").port_channels[1]
    used = {pc.select_egress(f"aa:bb:cc:00:00:{i:02x}", "11:22:33:44:55:66", "src-dst-mac")
            for i in range(20)}
    assert used == {"Fa0/23", "Fa0/24"}
