"""
Err-disable framework and the MAC address table.

    PC1 eth0 ── Fa0/1 SW1 Fa0/24 ──── Fa0/24 SW2 Fa0/1 ── eth0 PC2
                      SW1 Fa0/2  ── eth0 PC3

Lab time is advanced explicitly with ``sim.advance_time`` (the API does it
from the wall clock).
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel, InterfaceState

_seed = iter(range(3000, 99999))


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
    for d in (_pc("pc1", "10.0.0.1/24"), _pc("pc2", "10.0.0.2/24"), _pc("pc3", "10.0.0.3/24"),
              _switch("sw1"), _switch("sw2")):
        topo.add_device(d)
    for n, (a, ia, b, ib) in enumerate([("pc1", "eth0", "sw1", "Fa0/1"),
                                        ("pc2", "eth0", "sw2", "Fa0/1"),
                                        ("pc3", "eth0", "sw1", "Fa0/2"),
                                        ("sw1", "Fa0/24", "sw2", "Fa0/24")]):
        topo.add_link(Link(id=f"l{n}", endpoint_a=(a, ia), endpoint_b=(b, ib)))
    sim = Simulation(topo, seed=2)
    s = {d: CLISession(device_id=d, simulation=sim) for d in ("sw1", "sw2", "pc1")}
    for x in s.values():
        x.execute("enable")
    return sim, s


def _cfg(session: CLISession, *lines: str, iface: str | None = None) -> list[str]:
    session.execute("configure terminal")
    if iface:
        session.execute(f"interface {iface}")
    out = [session.execute(line) for line in lines]
    session.execute("end")
    return out


def _ping(s, ip: str = "10.0.0.2") -> str:
    out = s["pc1"].execute(f"ping {ip}")
    return next(l for l in out.splitlines() if l and set(l) <= {"!", "."})


def _port(sim, dev: str = "sw1", name: str = "Fa0/24"):
    return sim.topology.devices[dev].interfaces[name]


def _logs(sim, mnemonic: str) -> list[str]:
    return [e.message for e in sim.syslog if e.mnemonic == mnemonic]


def _guard_uplink(s):
    _cfg(s["sw1"], "spanning-tree portfast", "spanning-tree bpduguard enable", iface="FastEthernet0/24")


# ── BPDU guard → err-disable ─────────────────────────────────────────────────

def test_bpdu_guard_err_disables_a_port_facing_a_switch(lab):
    sim, s = lab
    assert _ping(s) == "!!!!!"
    _guard_uplink(s)
    port = _port(sim)
    assert port.err_disabled == "bpduguard"
    assert port.oper_state == InterfaceState.DOWN
    assert _port(sim, "sw2").oper_state == InterfaceState.DOWN      # the far end sees the link drop
    assert _logs(sim, "BLOCK_BPDUGUARD") == [
        "Received BPDU on port Fa0/24 with BPDU Guard enabled. Disabling port."]
    assert _logs(sim, "ERR_DISABLE") == [
        "bpduguard error detected on Fa0/24, putting Fa0/24 in err-disable state"]
    assert _ping(s) == "....."


def test_bpdu_guard_on_a_host_port_does_not_trip(lab):
    sim, s = lab
    _cfg(s["sw1"], "spanning-tree portfast", "spanning-tree bpduguard enable", iface="FastEthernet0/1")
    assert _port(sim, name="Fa0/1").err_disabled is None
    assert _ping(s) == "!!!!!"


def test_peer_bpdu_filter_keeps_the_guard_quiet(lab):
    sim, s = lab
    _cfg(s["sw2"], "spanning-tree bpdufilter enable", iface="FastEthernet0/24")
    _guard_uplink(s)
    assert _port(sim).err_disabled is None


def test_show_commands_for_an_err_disabled_port(lab):
    _, s = lab
    _guard_uplink(s)
    status = s["sw1"].execute("show interfaces status err-disabled").splitlines()
    assert status[0].split()[:4] == ["Port", "Name", "Status", "Reason"]
    assert status[1].split() == ["Fa0/24", "err-disabled", "bpduguard"]
    assert len(status) == 2
    assert s["sw1"].execute("show interfaces fa0/24").splitlines()[0] == \
        "FastEthernet0/24 is down, line protocol is down (err-disabled)"
    row = next(l for l in s["sw1"].execute("show interfaces status").splitlines()
               if l.startswith("Fa0/24"))
    assert "err-disabled" in row


def test_shutdown_no_shutdown_recovers_once_the_cause_is_gone(lab):
    sim, s = lab
    _guard_uplink(s)
    # Cause still there: the port goes straight back to err-disabled.
    _cfg(s["sw1"], "shutdown", "no shutdown", iface="FastEthernet0/24")
    assert _port(sim).err_disabled == "bpduguard"
    _cfg(s["sw1"], "no spanning-tree bpduguard enable", "shutdown", "no shutdown",
         iface="FastEthernet0/24")
    assert _port(sim).err_disabled is None
    assert _port(sim).oper_state == InterfaceState.UP
    assert _ping(s) == "!!!!!"


# ── errdisable recovery ──────────────────────────────────────────────────────

def test_no_automatic_recovery_by_default(lab):
    sim, s = lab
    _guard_uplink(s)
    sim.advance_time(3600)
    assert _port(sim).err_disabled == "bpduguard"


def test_recovery_timer_re_enables_the_port(lab):
    sim, s = lab
    _guard_uplink(s)
    _cfg(s["sw1"], "errdisable recovery cause bpduguard", "errdisable recovery interval 30")
    _cfg(s["sw1"], "no spanning-tree bpduguard enable", iface="FastEthernet0/24")
    sim.advance_time(29)
    assert _port(sim).err_disabled == "bpduguard"
    sim.advance_time(1)
    assert _port(sim).err_disabled is None
    assert _logs(sim, "ERR_RECOVER") == [
        "Attempting to recover from bpduguard err-disable state on Fa0/24"]
    assert _ping(s) == "!!!!!"


def test_recovery_with_the_cause_still_present_flaps(lab):
    sim, s = lab
    _guard_uplink(s)
    _cfg(s["sw1"], "errdisable recovery cause bpduguard", "errdisable recovery interval 30")
    sim.advance_time(30)
    assert _port(sim).err_disabled == "bpduguard"
    assert len(_logs(sim, "ERR_RECOVER")) == 1
    assert len(_logs(sim, "ERR_DISABLE")) == 2


def test_show_errdisable_recovery(lab):
    sim, s = lab
    _guard_uplink(s)
    _cfg(s["sw1"], "errdisable recovery cause bpduguard", "errdisable recovery interval 60")
    sim.advance_time(15)
    out = s["sw1"].execute("show errdisable recovery")
    assert "bpduguard                    Enabled" in out
    assert "psecure-violation            Disabled" in out
    assert "Timer interval: 60 seconds" in out
    row = next(l for l in out.splitlines() if l.startswith("Fa0/24"))
    assert row.split() == ["Fa0/24", "bpduguard", "45"]


def test_recovery_config_commands_and_running_config(lab):
    sim, s = lab
    sw1 = sim.get_switch("sw1")
    assert "Invalid input" in _cfg(s["sw1"], "errdisable recovery interval 10")[0]
    _cfg(s["sw1"], "errdisable recovery cause all", "errdisable recovery interval 45")
    assert "udld" in sw1.errdisable_recovery and len(sw1.errdisable_recovery) == 20
    _cfg(s["sw1"], "no errdisable recovery cause udld")
    assert "udld" not in sw1.errdisable_recovery
    run = s["sw1"].execute("show running-config")
    assert "errdisable recovery cause bpduguard" in run
    assert "errdisable recovery cause udld" not in run
    assert "errdisable recovery interval 45" in run
    _cfg(s["sw1"], "no errdisable recovery interval")
    assert sw1.errdisable_interval == 300


# ── MAC address table ────────────────────────────────────────────────────────

def test_static_entry_is_listed_and_used_for_forwarding(lab):
    sim, s = lab
    pc2_mac = sim.topology.devices["pc2"].interfaces["eth0"].mac.value
    cisco = pc2_mac.replace(":", "")
    cisco = f"{cisco[0:4]}.{cisco[4:8]}.{cisco[8:12]}"
    # Point PC2's address at the wrong port: unicast to PC2 now goes to Fa0/2.
    assert _cfg(s["sw1"], f"mac address-table static {cisco} vlan 1 interface Fa0/2") == [""]
    assert _ping(s) == "....."
    out = s["sw1"].execute("show mac address-table static")
    assert f"   1    {cisco}    STATIC      Fa0/2" in out
    # Learning never overwrites a static entry
    assert sim.get_switch("sw1").mac_lookup(pc2_mac, 1) == "Fa0/2"
    _cfg(s["sw1"], f"no mac address-table static {cisco} vlan 1 interface Fa0/2")
    assert _ping(s) == "!!!!!"


def test_static_entry_validation(lab):
    _, s = lab
    assert "Only unicast" in _cfg(s["sw1"], "mac address-table static 0100.5e00.0001 vlan 1 interface Fa0/2")[0]
    assert "Invalid input" in _cfg(s["sw1"], "mac address-table static 0000.1111 vlan 1 interface Fa0/2")[0]
    assert "Invalid input" in _cfg(s["sw1"], "mac address-table static 0000.1111.2222 vlan 5000 interface Fa0/2")[0]
    assert _cfg(s["sw1"], "mac address-table static 0000.1111.2222 vlan 1")[0] == "% Incomplete command."


def test_dynamic_entries_age_out(lab):
    sim, s = lab
    _ping(s)
    table = sim.get_switch("sw1").mac_table
    assert len(table) == 2
    sim.advance_time(299)
    assert len(sim.get_switch("sw1").mac_table) == 2
    sim.advance_time(1)
    assert sim.get_switch("sw1").mac_table == {}


def test_aging_time_setting(lab):
    sim, s = lab
    assert "Invalid input" in _cfg(s["sw1"], "mac address-table aging-time 5")[0]
    _cfg(s["sw1"], "mac address-table aging-time 0")          # 0 = never age
    _ping(s)
    sim.advance_time(10_000)
    assert len(sim.get_switch("sw1").mac_table) == 2
    _cfg(s["sw1"], "mac address-table aging-time 20")
    assert s["sw1"].execute("show mac address-table aging-time").splitlines()[0] == "Global Aging Time:   20"
    assert "mac address-table aging-time 20" in s["sw1"].execute("show running-config")
    sim.advance_time(20)
    assert sim.get_switch("sw1").mac_table == {}
    _cfg(s["sw1"], "no mac address-table aging-time")
    assert sim.get_switch("sw1").mac_aging_time == 300


def test_link_down_flushes_the_ports_entries(lab):
    sim, s = lab
    _ping(s)
    _cfg(s["sw1"], "shutdown", iface="FastEthernet0/24")
    assert set(sim.get_switch("sw1").mac_table.values()) == {"Fa0/1"}


def test_clear_mac_address_table_filters(lab):
    sim, s = lab
    _ping(s)
    _ping(s, "10.0.0.3")
    sw1 = sim.get_switch("sw1")
    assert len(sw1.mac_table) == 3
    s["sw1"].execute("clear mac address-table dynamic interface Fa0/2")
    assert "Fa0/2" not in sw1.mac_table.values() and len(sw1.mac_table) == 2
    s["sw1"].execute("clear mac address-table dynamic vlan 99")
    assert len(sw1.mac_table) == 2
    s["sw1"].execute("clear mac address-table dynamic")
    assert sw1.mac_table == {}


def test_show_mac_address_table_filters_and_count(lab):
    sim, s = lab
    _ping(s)
    _cfg(s["sw1"], "mac address-table static 0000.1111.2222 vlan 1 interface Fa0/5")
    full = s["sw1"].execute("show mac address-table")
    assert full.endswith("Total Mac Addresses for this criterion: 3")
    assert s["sw1"].execute("show mac address-table dynamic").endswith("criterion: 2")
    assert s["sw1"].execute("show mac address-table interface Fa0/5").endswith("criterion: 1")
    assert s["sw1"].execute("show mac address-table address 0000.1111.2222").endswith("criterion: 1")
    assert s["sw1"].execute("show mac address-table vlan 1 ").endswith("criterion: 3")
    count = s["sw1"].execute("show mac address-table count")
    assert "Dynamic Address Count  : 2" in count and "Static  Address Count  : 1" in count
    assert "mac address-table static 0000.1111.2222 vlan 1 interface FastEthernet0/5" in \
        s["sw1"].execute("show running-config")
