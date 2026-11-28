"""A PC can be started without an address and configured from its console."""

from __future__ import annotations

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel


@pytest.fixture()
def lab():
    topo = Topology()
    for n, dev_id in enumerate(("pc1", "pc2")):
        pc = Device(id=dev_id, model=DeviceModel.HOST, hostname=dev_id.upper())
        pc.add_interface(Interface(name="eth0", mac=MACAddress(f"aa:00:00:00:00:{n + 1:02x}")))
        topo.add_device(pc)
    sw = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
    for n in range(1, 3):
        sw.add_interface(Interface(name=f"Fa0/{n}", mac=MACAddress(f"aa:00:00:00:01:{n:02x}")))
    topo.add_device(sw)
    topo.add_link(Link(id="l1", endpoint_a=("pc1", "eth0"), endpoint_b=("sw1", "Fa0/1")))
    topo.add_link(Link(id="l2", endpoint_a=("pc2", "eth0"), endpoint_b=("sw1", "Fa0/2")))
    sim = Simulation(topo, seed=1)
    return sim, {d: CLISession(device_id=d, simulation=sim) for d in ("pc1", "pc2", "sw1")}


def test_unaddressed_pc_shows_zero_address(lab):
    _, s = lab
    out = s["pc1"].execute("ipconfig")
    assert "IPv4 Address....................: 0.0.0.0" in out


def test_ipconfig_sets_address_and_gateway(lab):
    sim, s = lab
    assert s["pc1"].execute("ipconfig 192.168.1.10 255.255.255.0 192.168.1.1") == ""
    assert s["pc2"].execute("ipconfig 192.168.1.20/24") == ""
    eth0 = sim.topology.devices["pc1"].interfaces["eth0"]
    assert str(eth0.ip_config.address) == "192.168.1.10" and eth0.ip_config.prefix_length == 24
    assert eth0.default_gateway == "192.168.1.1"
    out = s["pc1"].execute("ipconfig")
    assert "192.168.1.10" in out and "255.255.255.0" in out and "192.168.1.1" in out
    ping = s["pc1"].execute("ping 192.168.1.20")
    assert "!!!!!" in ping


def test_ipconfig_rejects_bad_input(lab):
    _, s = lab
    assert "Invalid input" in s["pc1"].execute("ipconfig 300.1.1.1 255.255.255.0")
    assert "Bad mask" in s["pc1"].execute("ipconfig 192.168.1.10 255.0.255.0")
    assert "Incomplete" in s["pc1"].execute("ipconfig 192.168.1.10")


def test_ipconfig_is_only_on_pcs(lab):
    _, s = lab
    assert "Invalid input" in s["sw1"].execute("ipconfig")
    assert "ipconfig" in s["pc1"].execute("?")
