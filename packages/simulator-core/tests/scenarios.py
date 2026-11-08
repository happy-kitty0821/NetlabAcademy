"""
tests/scenarios.py
------------------
Reusable scenario builders for integration tests.

These helpers are test-layer utilities only.  They are not part of the
simulator_core public API.
"""

from __future__ import annotations

import random
from typing import Optional

from simulator_core.addresses import MACAddress
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel


def _mac(seed: int) -> MACAddress:
    return MACAddress.generate(random.Random(seed))


def build_two_host_topology(
    rng: random.Random,
) -> tuple[Topology, str, str, str]:
    """
    Build the standard PoC topology: Host-A — Switch — Host-B.

    Returns
    -------
    topology, host_a_id, host_b_id, switch_id
    """
    topo = Topology()

    ha = Device(id="host-a", model=DeviceModel.HOST, hostname="PC-A")
    ha.add_interface(Interface(name="eth0", mac=MACAddress.generate(rng)))

    hb = Device(id="host-b", model=DeviceModel.HOST, hostname="PC-B")
    hb.add_interface(Interface(name="eth0", mac=MACAddress.generate(rng)))

    sw = Device(id="switch-1", model=DeviceModel.SWITCH, hostname="SW1")
    sw.add_interface(Interface(name="Gi0/0", mac=MACAddress.generate(rng)))
    sw.add_interface(Interface(name="Gi0/1", mac=MACAddress.generate(rng)))

    topo.add_device(ha)
    topo.add_device(hb)
    topo.add_device(sw)

    topo.add_link(Link(
        id="link-a-sw",
        endpoint_a=("host-a", "eth0"),
        endpoint_b=("switch-1", "Gi0/0"),
    ))
    topo.add_link(Link(
        id="link-b-sw",
        endpoint_a=("host-b", "eth0"),
        endpoint_b=("switch-1", "Gi0/1"),
    ))

    return topo, "host-a", "host-b", "switch-1"


def configure_same_subnet(
    topology: Topology,
    host_a_id: str,
    ip_a: str,
    host_b_id: str,
    ip_b: str,
) -> None:
    """
    Assign IPv4 addresses to host_a and host_b.
    Both must be valid host addresses (callers ensure they are on the same /24).
    """
    topology.devices[host_a_id].interfaces["eth0"].set_ip(ip_a)
    topology.devices[host_b_id].interfaces["eth0"].set_ip(ip_b)


def build_sim(seed: int = 42) -> Simulation:
    """
    Build and return a Simulation with the standard two-host-one-switch
    topology, both hosts configured on 192.168.1.0/24.
    """
    rng = random.Random(seed)
    topo, ha, hb, sw = build_two_host_topology(rng)
    configure_same_subnet(topo, ha, "192.168.1.1/24", hb, "192.168.1.2/24")
    return Simulation(topo, seed=seed)
