"""
tests/test_topology.py
----------------------
Unit tests for Interface, Device, Link and Topology.

Covers: valid construction, error cases (dup IDs, self-link, bad endpoints,
node/link cap), neighbours() and get_link() queries.
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.exceptions import TopologyError
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel, InterfaceState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mac(seed: int) -> MACAddress:
    return MACAddress.generate(random.Random(seed))


def _make_host(device_id: str, hostname: str, mac_seed: int) -> Device:
    device = Device(id=device_id, model=DeviceModel.HOST, hostname=hostname)
    iface = Interface(name="eth0", mac=_mac(mac_seed))
    device.add_interface(iface)
    return device


def _make_switch(device_id: str, hostname: str, port_count: int, mac_seed_start: int) -> Device:
    device = Device(id=device_id, model=DeviceModel.SWITCH, hostname=hostname)
    for i in range(port_count):
        iface = Interface(name=f"Gi0/{i}", mac=_mac(mac_seed_start + i))
        device.add_interface(iface)
    return device


def build_two_host_one_switch() -> Topology:
    """Standard PoC topology: host-a — switch — host-b."""
    topo = Topology()
    ha = _make_host("host-a", "PC-A", mac_seed=10)
    hb = _make_host("host-b", "PC-B", mac_seed=11)
    sw = _make_switch("switch-1", "SW1", port_count=2, mac_seed_start=20)
    topo.add_device(ha)
    topo.add_device(hb)
    topo.add_device(sw)
    topo.add_link(Link(id="link-1", endpoint_a=("host-a", "eth0"), endpoint_b=("switch-1", "Gi0/0")))
    topo.add_link(Link(id="link-2", endpoint_a=("host-b", "eth0"), endpoint_b=("switch-1", "Gi0/1")))
    return topo


# =============================================================================
# Valid topology construction
# =============================================================================


class TestTopologyValidConstruction:
    def test_two_host_one_switch_validates(self) -> None:
        topo = build_two_host_one_switch()
        topo.validate()  # must not raise

    def test_device_count(self) -> None:
        topo = build_two_host_one_switch()
        assert len(topo.devices) == 3

    def test_link_count(self) -> None:
        topo = build_two_host_one_switch()
        assert len(topo.links) == 2

    def test_neighbours_host_a_to_switch(self) -> None:
        topo = build_two_host_one_switch()
        peer = topo.neighbours("host-a", "eth0")
        assert peer == ("switch-1", "Gi0/0")

    def test_neighbours_switch_to_host_a(self) -> None:
        topo = build_two_host_one_switch()
        peer = topo.neighbours("switch-1", "Gi0/0")
        assert peer == ("host-a", "eth0")

    def test_neighbours_none_for_unconnected(self) -> None:
        topo = build_two_host_one_switch()
        # Add a device with an unconnected interface.
        lone = _make_host("lone", "Lone", mac_seed=99)
        topo.add_device(lone)
        topo.validate()
        assert topo.neighbours("lone", "eth0") is None

    def test_get_link_returns_correct_link(self) -> None:
        topo = build_two_host_one_switch()
        link = topo.get_link("host-a", "eth0")
        assert link is not None
        assert link.id == "link-1"

    def test_get_link_none_for_unconnected(self) -> None:
        topo = Topology()
        lone = _make_host("lone", "Lone", mac_seed=1)
        topo.add_device(lone)
        assert topo.get_link("lone", "eth0") is None


# =============================================================================
# Validation errors
# =============================================================================


class TestTopologyValidationErrors:
    def test_empty_topology_raises(self) -> None:
        topo = Topology()
        with pytest.raises(TopologyError, match="at least one device"):
            topo.validate()

    def test_duplicate_device_id_raises(self) -> None:
        topo = Topology()
        ha = _make_host("host-a", "PC-A", mac_seed=1)
        ha_dup = _make_host("host-a", "PC-A-dup", mac_seed=2)
        topo.add_device(ha)
        with pytest.raises(TopologyError, match="already contains"):
            topo.add_device(ha_dup)

    def test_duplicate_interface_name_on_device_raises(self) -> None:
        device = Device(id="d1", model=DeviceModel.HOST, hostname="D1")
        iface1 = Interface(name="eth0", mac=_mac(1))
        iface2 = Interface(name="eth0", mac=_mac(2))
        device.add_interface(iface1)
        with pytest.raises(TopologyError, match="duplicate interface name"):
            device.add_interface(iface2)

    def test_self_link_raises(self) -> None:
        topo = Topology()
        sw = _make_switch("sw1", "SW1", port_count=2, mac_seed_start=10)
        topo.add_device(sw)
        topo.add_link(Link(
            id="self-link",
            endpoint_a=("sw1", "Gi0/0"),
            endpoint_b=("sw1", "Gi0/1"),
        ))
        with pytest.raises(TopologyError, match="self-link"):
            topo.validate()

    def test_missing_device_in_link_raises(self) -> None:
        topo = Topology()
        ha = _make_host("host-a", "PC-A", mac_seed=1)
        topo.add_device(ha)
        topo.add_link(Link(
            id="link-bad",
            endpoint_a=("host-a", "eth0"),
            endpoint_b=("nonexistent", "eth0"),
        ))
        with pytest.raises(TopologyError, match="non-existent device"):
            topo.validate()

    def test_missing_interface_in_link_raises(self) -> None:
        topo = Topology()
        ha = _make_host("host-a", "PC-A", mac_seed=1)
        hb = _make_host("host-b", "PC-B", mac_seed=2)
        topo.add_device(ha)
        topo.add_device(hb)
        topo.add_link(Link(
            id="link-bad",
            endpoint_a=("host-a", "eth0"),
            endpoint_b=("host-b", "no-such-iface"),
        ))
        with pytest.raises(TopologyError, match="non-existent interface"):
            topo.validate()

    def test_interface_in_two_links_raises(self) -> None:
        topo = Topology()
        ha = _make_host("host-a", "PC-A", mac_seed=1)
        hb = _make_host("host-b", "PC-B", mac_seed=2)
        sw = _make_switch("sw1", "SW1", port_count=2, mac_seed_start=10)
        topo.add_device(ha)
        topo.add_device(hb)
        topo.add_device(sw)
        topo.add_link(Link(id="l1", endpoint_a=("host-a", "eth0"), endpoint_b=("sw1", "Gi0/0")))
        topo.add_link(Link(id="l2", endpoint_a=("host-a", "eth0"), endpoint_b=("sw1", "Gi0/1")))
        with pytest.raises(TopologyError, match="more than one link"):
            topo.validate()

    def test_node_cap_raises_on_add(self) -> None:
        topo = Topology(max_nodes=2)
        topo.add_device(_make_host("h1", "H1", mac_seed=1))
        topo.add_device(_make_host("h2", "H2", mac_seed=2))
        with pytest.raises(TopologyError, match="node limit"):
            topo.add_device(_make_host("h3", "H3", mac_seed=3))

    def test_link_cap_raises_on_add(self) -> None:
        topo = Topology(max_links=1)
        ha = _make_host("host-a", "PC-A", mac_seed=1)
        hb = _make_host("host-b", "PC-B", mac_seed=2)
        sw = _make_switch("sw1", "SW1", port_count=2, mac_seed_start=10)
        topo.add_device(ha)
        topo.add_device(hb)
        topo.add_device(sw)
        topo.add_link(Link(id="l1", endpoint_a=("host-a", "eth0"), endpoint_b=("sw1", "Gi0/0")))
        with pytest.raises(TopologyError, match="link limit"):
            topo.add_link(Link(id="l2", endpoint_a=("host-b", "eth0"), endpoint_b=("sw1", "Gi0/1")))


# =============================================================================
# Device helpers
# =============================================================================


class TestDeviceHelpers:
    def test_get_interface_exists(self) -> None:
        device = _make_host("d1", "D1", mac_seed=1)
        iface = device.get_interface("eth0")
        assert iface.name == "eth0"

    def test_get_interface_missing_raises(self) -> None:
        device = _make_host("d1", "D1", mac_seed=1)
        with pytest.raises(TopologyError):
            device.get_interface("eth99")


# =============================================================================
# Interface IP configuration
# =============================================================================


class TestInterfaceIPConfig:
    def test_set_ip_valid(self) -> None:
        iface = Interface(name="eth0", mac=_mac(1))
        iface.set_ip("192.168.1.1/24")
        assert iface.ip_config is not None
        assert str(iface.ip_config.address) == "192.168.1.1"

    def test_set_ip_invalid_raises(self) -> None:
        from simulator_core.exceptions import ConfigurationError

        iface = Interface(name="eth0", mac=_mac(1))
        with pytest.raises(ConfigurationError):
            iface.set_ip("999.0.0.1/24")

    def test_set_gateway_valid(self) -> None:
        iface = Interface(name="eth0", mac=_mac(1))
        iface.set_gateway("192.168.1.254")
        assert iface.default_gateway == "192.168.1.254"

    def test_set_gateway_invalid_raises(self) -> None:
        from simulator_core.exceptions import ConfigurationError

        iface = Interface(name="eth0", mac=_mac(1))
        with pytest.raises(ConfigurationError):
            iface.set_gateway("not.an.ip")
