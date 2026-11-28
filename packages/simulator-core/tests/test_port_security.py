"""
switchport port-security on a Catalyst 2960.

    PC1 eth0 ── Fa0/1 SW1 Fa0/2 ── eth0 PC2
                      SW1 Fa0/3 ── (spare, PC3 is cabled here when needed)

Cable moves (unplugging PC1 and plugging PC3 into Fa0/1) produce the
classic "unknown device on a secure port" violation.
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel, InterfaceState

_seed = iter(range(5000, 99999))


def _mac() -> MACAddress:
    return MACAddress.generate(random.Random(next(_seed)))


def _pc(dev_id: str, ip: str) -> Device:
    d = Device(id=dev_id, model=DeviceModel.HOST, hostname=dev_id.upper())
    d.add_interface(Interface(name="eth0", mac=_mac()))
    d.interfaces["eth0"].set_ip(ip)
    return d


@pytest.fixture()
def lab():
    sw = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
    for i in range(1, 25):
        sw.add_interface(Interface(name=f"Fa0/{i}", mac=_mac()))
    topo = Topology()
    for d in (_pc("pc1", "10.0.0.1/24"), _pc("pc2", "10.0.0.2/24"), _pc("pc3", "10.0.0.3/24"), sw):
        topo.add_device(d)
    topo.add_link(Link(id="l1", endpoint_a=("pc1", "eth0"), endpoint_b=("sw1", "Fa0/1")))
    topo.add_link(Link(id="l2", endpoint_a=("pc2", "eth0"), endpoint_b=("sw1", "Fa0/2")))
    sim = Simulation(topo, seed=4)
    s = {d: CLISession(device_id=d, simulation=sim) for d in ("sw1", "pc1", "pc3")}
    s["sw1"].execute("enable")
    return sim, s


def _cfg(s, *lines: str, iface: str = "FastEthernet0/1") -> list[str]:
    s["sw1"].execute("configure terminal")
    s["sw1"].execute(f"interface {iface}")
    out = [s["sw1"].execute(line) for line in lines]
    s["sw1"].execute("end")
    return out


def _ping(s, src: str = "pc1", ip: str = "10.0.0.2") -> str:
    out = s[src].execute(f"ping {ip}")
    return next(l for l in out.splitlines() if l and set(l) <= {"!", "."})


def _swap_in_pc3(sim, port: str = "Fa0/1") -> None:
    """Unplug PC1 and plug PC3 into the same port."""
    sim.remove_link("l1")
    sim.add_link(Link(id="l9", endpoint_a=("pc3", "eth0"), endpoint_b=("sw1", port)))


def _secure(s, *extra: str) -> None:
    _cfg(s, "switchport mode access", "switchport port-security", *extra)


def _mac_of(sim, dev: str) -> str:
    return sim.topology.devices[dev].interfaces["eth0"].mac.value


def _cisco(mac: str) -> str:
    d = mac.replace(":", "")
    return f"{d[0:4]}.{d[4:8]}.{d[8:12]}"


def _psec(sim, port: str = "Fa0/1"):
    return sim.get_switch("sw1").port_security_config(port)


def _logs(sim, mnemonic: str) -> list[str]:
    return [e.message for e in sim.syslog if e.mnemonic == mnemonic]


# ── Learning ──────────────────────────────────────────────────────────────────

def test_first_address_is_learned_and_traffic_flows(lab):
    sim, s = lab
    _secure(s)
    assert _ping(s) == "!!!!!"
    ps = _psec(sim)
    assert list(ps.addresses) == [(_mac_of(sim, "pc1"), 1)]
    assert ps.addresses[(_mac_of(sim, "pc1"), 1)].kind == "SecureDynamic"
    # Secure addresses show as STATIC in the MAC table
    row = next(l for l in s["sw1"].execute("show mac address-table").splitlines() if "Fa0/1" in l)
    assert "STATIC" in row


def test_dynamic_secure_address_is_forgotten_when_the_link_drops(lab):
    sim, s = lab
    _secure(s)
    _ping(s)
    _cfg(s, "shutdown")
    assert _psec(sim).addresses == {}


def test_sticky_addresses_survive_and_appear_in_running_config(lab):
    sim, s = lab
    _secure(s, "switchport port-security mac-address sticky")
    _ping(s)
    _cfg(s, "shutdown", "no shutdown")
    mac = _cisco(_mac_of(sim, "pc1"))
    run = s["sw1"].execute("show running-config interface fa0/1")
    assert run.splitlines()[5:9] == [
        " switchport mode access",
        " switchport port-security",
        " switchport port-security mac-address sticky",
        f" switchport port-security mac-address sticky {mac}",
    ]


def test_turning_sticky_on_converts_learned_addresses(lab):
    sim, s = lab
    _secure(s)
    _ping(s)
    _cfg(s, "switchport port-security mac-address sticky")
    assert _psec(sim).count("SecureSticky") == 1
    _cfg(s, "no switchport port-security mac-address sticky")
    assert _psec(sim).count("SecureSticky") == 0 and _psec(sim).count("SecureDynamic") == 1


# ── Violations ────────────────────────────────────────────────────────────────

def test_shutdown_violation_err_disables_the_port(lab):
    sim, s = lab
    _secure(s, "switchport port-security mac-address sticky")
    _ping(s)
    _swap_in_pc3(sim)
    assert _ping(s, "pc3") == "....."
    port = sim.topology.devices["sw1"].interfaces["Fa0/1"]
    assert port.err_disabled == "psecure-violation"
    assert port.oper_state == InterfaceState.DOWN
    assert _logs(sim, "ERR_DISABLE") == [
        "psecure-violation error detected on Fa0/1, putting Fa0/1 in err-disable state"]
    assert _logs(sim, "PSECURE_VIOLATION") == [
        f"Security violation occurred, caused by MAC address {_cisco(_mac_of(sim, 'pc3'))} "
        f"on port FastEthernet0/1."]
    detail = s["sw1"].execute("show port-security interface fa0/1")
    assert "Port Status                : Secure-shutdown" in detail
    assert "Security Violation Count   : 1" in detail
    assert f"Last Source Address:Vlan   : {_cisco(_mac_of(sim, 'pc3'))}:1" in detail


def test_restrict_drops_counts_and_logs_but_stays_up(lab):
    sim, s = lab
    _secure(s, "switchport port-security violation restrict",
            "switchport port-security mac-address sticky")   # survives the unplug
    _ping(s)
    _swap_in_pc3(sim)
    assert _ping(s, "pc3") == "....."
    ps = _psec(sim)
    assert ps.violation_count >= 1
    assert _logs(sim, "PSECURE_VIOLATION")
    assert sim.topology.devices["sw1"].interfaces["Fa0/1"].err_disabled is None


def test_protect_drops_silently(lab):
    sim, s = lab
    _secure(s, "switchport port-security violation protect",
            "switchport port-security mac-address sticky")   # survives the unplug
    _ping(s)
    _swap_in_pc3(sim)
    assert _ping(s, "pc3") == "....."
    assert _psec(sim).violation_count == 0
    assert _logs(sim, "PSECURE_VIOLATION") == []


def test_maximum_allows_more_devices(lab):
    sim, s = lab
    _secure(s, "switchport port-security maximum 2")
    _ping(s)
    _swap_in_pc3(sim)
    assert _ping(s, "pc3") == "!!!!!"
    assert len(_psec(sim).addresses) == 1        # PC1's dynamic entry went with the link
    assert sim.topology.devices["sw1"].interfaces["Fa0/1"].err_disabled is None


def test_mac_move_between_secure_ports_is_a_violation(lab):
    sim, s = lab
    _secure(s, "switchport port-security mac-address sticky")
    _cfg(s, "switchport mode access", "switchport port-security", iface="FastEthernet0/3")
    _ping(s)
    # PC1 moves from Fa0/1 to Fa0/3: its address is still secure on Fa0/1.
    sim.remove_link("l1")
    sim.add_link(Link(id="l9", endpoint_a=("pc1", "eth0"), endpoint_b=("sw1", "Fa0/3")))
    assert _ping(s) == "....."
    assert sim.topology.devices["sw1"].interfaces["Fa0/3"].err_disabled == "psecure-violation"


def test_recovery_after_a_violation(lab):
    sim, s = lab
    _secure(s, "switchport port-security mac-address sticky")
    _ping(s)
    _swap_in_pc3(sim)
    _ping(s, "pc3")
    s["sw1"].execute("clear port-security sticky interface Fa0/1")
    _cfg(s, "shutdown", "no shutdown")
    assert _ping(s, "pc3") == "!!!!!"


# ── Configured addresses and validation ───────────────────────────────────────

def test_configured_address_only_admits_that_device(lab):
    sim, s = lab
    pc3 = _cisco(_mac_of(sim, "pc3"))
    _secure(s, f"switchport port-security mac-address {pc3}")
    assert _ping(s) == "....."                     # PC1 is not the configured device
    assert sim.topology.devices["sw1"].interfaces["Fa0/1"].err_disabled == "psecure-violation"
    assert f" switchport port-security mac-address {pc3}" in \
        s["sw1"].execute("show running-config interface fa0/1")


def test_config_validation(lab):
    sim, s = lab
    assert _cfg(s, "switchport mode dynamic auto", "switchport port-security")[1] == \
        "Command rejected: FastEthernet0/1 is a dynamic port."
    _cfg(s, "switchport mode access", "switchport port-security",
         "switchport port-security mac-address 0000.1111.2222")
    assert _cfg(s, "switchport port-security mac-address 0000.1111.3333")[0] == \
        "Total secure mac-addresses on interface FastEthernet0/1 has reached maximum limit."
    out = _cfg(s, "switchport mode access", "switchport port-security",
               "switchport port-security mac-address 0000.1111.2222", iface="FastEthernet0/3")
    assert out[2] == "Found duplicate mac-address 0000.1111.2222."
    assert "Invalid input" in _cfg(s, "switchport port-security maximum 200")[0]


def test_no_forms_reset_settings(lab):
    sim, s = lab
    _secure(s, "switchport port-security maximum 4", "switchport port-security violation restrict",
            "switchport port-security aging time 5")
    ps = _psec(sim)
    assert (ps.maximum, ps.violation, ps.aging_time) == (4, "restrict", 5)
    _cfg(s, "no switchport port-security maximum", "no switchport port-security violation",
         "no switchport port-security aging time", "no switchport port-security")
    assert (ps.maximum, ps.violation, ps.aging_time, ps.enabled) == (1, "shutdown", 0, False)


def test_secure_dynamic_addresses_age(lab):
    sim, s = lab
    _secure(s, "switchport port-security aging time 2")
    _ping(s)
    sim.advance_time(119)
    assert len(_psec(sim).addresses) == 1
    sim.advance_time(1)
    assert _psec(sim).addresses == {}


# ── show / clear ──────────────────────────────────────────────────────────────

def test_show_port_security_summary_and_addresses(lab):
    sim, s = lab
    _secure(s, "switchport port-security maximum 2", "switchport port-security mac-address sticky")
    _ping(s)
    summary = s["sw1"].execute("show port-security").splitlines()
    assert summary[0].startswith("Secure Port  MaxSecureAddr  CurrentAddr")
    assert summary[3].split() == ["Fa0/1", "2", "1", "0", "Shutdown"]
    assert summary[-2] == "Total Addresses in System (excluding one mac per port)     : 0"
    addresses = s["sw1"].execute("show port-security address")
    row = next(l for l in addresses.splitlines() if "Fa0/1" in l)
    assert row.split() == ["1", _cisco(_mac_of(sim, "pc1")), "SecureSticky", "Fa0/1", "-"]


def test_clear_port_security(lab):
    sim, s = lab
    _secure(s, "switchport port-security maximum 3", "switchport port-security mac-address 0000.1111.2222")
    _ping(s)
    assert len(_psec(sim).addresses) == 2
    s["sw1"].execute("clear port-security dynamic")
    assert list(a.kind for a in _psec(sim).addresses.values()) == ["SecureConfigured"]
    s["sw1"].execute("clear port-security all address 0000.1111.2222")
    assert _psec(sim).addresses == {}
