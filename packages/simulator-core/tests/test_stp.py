"""
tests/test_stp.py
-----------------
Tests for STP, 802.1Q trunking, and EtherChannel.
"""

from __future__ import annotations

import random
import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cli import CLISession, CLIMode
from simulator_core.simulation import Simulation
from simulator_core.stp import (
    BridgeID, PortRole, PortState, STPManager, STPMode
)
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel


def _mac(seed: int) -> MACAddress:
    return MACAddress.generate(random.Random(seed))


def build_two_switch_topology() -> tuple[Topology, str, str]:
    """
    SW1 ── SW2  (trunk link between them, two host ports on each)
    """
    topo = Topology()

    sw1 = Device(id="sw1", model=DeviceModel.SWITCH, hostname="SW1")
    sw1.add_interface(Interface(name="Gi0/0", mac=_mac(1)))
    sw1.add_interface(Interface(name="Gi0/1", mac=_mac(2)))  # trunk to SW2
    sw1.add_interface(Interface(name="Gi0/2", mac=_mac(3)))
    sw1.add_interface(Interface(name="Gi0/3", mac=_mac(4)))

    sw2 = Device(id="sw2", model=DeviceModel.SWITCH, hostname="SW2")
    sw2.add_interface(Interface(name="Gi0/0", mac=_mac(5)))  # trunk to SW1
    sw2.add_interface(Interface(name="Gi0/1", mac=_mac(6)))
    sw2.add_interface(Interface(name="Gi0/2", mac=_mac(7)))
    sw2.add_interface(Interface(name="Gi0/3", mac=_mac(8)))

    topo.add_device(sw1)
    topo.add_device(sw2)
    topo.add_link(Link(id="trunk-sw1-sw2",
                       endpoint_a=("sw1", "Gi0/1"),
                       endpoint_b=("sw2", "Gi0/0")))

    return topo, "sw1", "sw2"


def make_switch_session(device_id: str = "sw1") -> CLISession:
    topo, _, _ = build_two_switch_topology()
    sim = Simulation(topo, seed=42)
    s = CLISession(device_id=device_id, simulation=sim)
    s.execute("enable")
    return s


# ── BridgeID ──────────────────────────────────────────────────────────────────


class TestBridgeID:
    def test_lower_priority_wins(self) -> None:
        a = BridgeID(priority=4096,  sys_id_ext=1, mac="aa:aa:aa:aa:aa:aa")
        b = BridgeID(priority=32768, sys_id_ext=1, mac="bb:bb:bb:bb:bb:bb")
        assert a < b

    def test_equal_priority_mac_tiebreak(self) -> None:
        a = BridgeID(priority=32768, sys_id_ext=1, mac="aa:aa:aa:aa:aa:aa")
        b = BridgeID(priority=32768, sys_id_ext=1, mac="bb:bb:bb:bb:bb:bb")
        assert a < b

    def test_bridge_priority_property(self) -> None:
        bid = BridgeID(priority=32768, sys_id_ext=10, mac="aa:bb:cc:dd:ee:ff")
        assert bid.bridge_priority == 32778


# ── STPManager ────────────────────────────────────────────────────────────────


class TestSTPManager:
    def test_initial_state_root(self) -> None:
        """A newly created switch assumes it is root."""
        stp = STPManager(device_id="sw1", mac="00:00:00:00:00:01")
        stp.ensure_vlan(1)
        inst = stp.get_instance(1)
        assert inst is not None
        assert inst.is_root

    def test_set_bridge_priority(self) -> None:
        stp = STPManager(device_id="sw1", mac="00:00:00:00:00:01")
        stp.set_bridge_priority(1, 4096)
        inst = stp.get_instance(1)
        assert inst.bridge_id.priority == 4096

    def test_invalid_priority_not_multiple_of_4096(self) -> None:
        stp = STPManager(device_id="sw1", mac="00:00:00:00:00:01")
        with pytest.raises(ValueError, match="multiple of 4096"):
            stp.set_bridge_priority(1, 100)

    def test_set_root_primary(self) -> None:
        stp = STPManager(device_id="sw1", mac="00:00:00:00:00:01")
        stp.set_root_primary(1)
        assert stp.get_instance(1).bridge_id.priority == 24576

    def test_set_root_secondary(self) -> None:
        stp = STPManager(device_id="sw1", mac="00:00:00:00:00:01")
        stp.set_root_secondary(1)
        assert stp.get_instance(1).bridge_id.priority == 28672

    def test_portfast_sets_forwarding(self) -> None:
        stp = STPManager(device_id="sw1", mac="00:00:00:00:00:01")
        stp.ensure_vlan(1)
        inst = stp.get_instance(1)
        # Create port
        port = stp._get_or_create_port(inst, "Gi0/0")
        port.state = PortState.BLOCKING
        stp.set_portfast("Gi0/0", True)
        assert stp.get_port_state("Gi0/0", 1) == PortState.FORWARDING

    def test_disable_stp_per_vlan(self) -> None:
        stp = STPManager(device_id="sw1", mac="00:00:00:00:00:01")
        stp.ensure_vlan(1)
        inst = stp.get_instance(1)
        stp._get_or_create_port(inst, "Gi0/0")
        stp.disable_stp(1)
        assert stp.get_port_state("Gi0/0", 1) == PortState.FORWARDING


# ── CLI STP commands ──────────────────────────────────────────────────────────


class TestSTPCLI:
    def test_stp_mode_rapid_pvst(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("spanning-tree mode rapid-pvst")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        assert switch.stp.mode == STPMode.RAPID_PVST

    def test_stp_mode_pvst(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("spanning-tree mode pvst")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        assert switch.stp.mode == STPMode.PVST

    def test_stp_vlan_priority(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("spanning-tree vlan 1 priority 4096")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        assert inst.bridge_id.priority == 4096

    def test_stp_vlan_root_primary(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("spanning-tree vlan 1 root primary")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        assert inst.bridge_id.priority == 24576

    def test_stp_vlan_root_secondary(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("spanning-tree vlan 1 root secondary")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        assert inst.bridge_id.priority == 28672

    def test_stp_portfast_on_interface(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/0")
        s.execute("spanning-tree portfast")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        port = inst.port_states.get("Gi0/0")
        assert port is not None
        assert port.portfast is True

    def test_stp_bpduguard_on_interface(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/0")
        s.execute("spanning-tree bpduguard enable")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        port = inst.port_states.get("Gi0/0")
        assert port is not None
        assert port.bpduguard is True

    def test_stp_port_cost(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/0")
        s.execute("spanning-tree cost 100")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        port = switch.stp._get_or_create_port(inst, "Gi0/0")
        assert port.path_cost == 100

    def test_show_spanning_tree(self) -> None:
        s = make_switch_session("sw1")
        out = s.execute("show spanning-tree")
        assert "VLAN0001" in out or "vlan" in out.lower()
        assert "Bridge ID" in out

    def test_show_spanning_tree_summary(self) -> None:
        s = make_switch_session("sw1")
        out = s.execute("show spanning-tree summary")
        assert "mode" in out.lower() or "Rapid" in out

    def test_invalid_stp_priority(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        out = s.execute("spanning-tree vlan 1 priority 100")
        assert "%" in out

    def test_stp_guard_root(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/0")
        s.execute("spanning-tree guard root")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        inst = switch.stp.get_instance(1)
        port = inst.port_states.get("Gi0/0")
        assert port is not None
        assert port.guard == "root"


# ── 802.1Q Trunking CLI ───────────────────────────────────────────────────────


class TestTrunkingCLI:
    def test_set_trunk_mode(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/1")
        s.execute("switchport mode trunk")
        s.execute("end")
        iface = s.simulation.topology.devices["sw1"].interfaces["Gi0/1"]
        assert iface.switchport_mode == "trunk"

    def test_set_access_mode(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/1")
        s.execute("switchport mode trunk")
        s.execute("switchport mode access")
        s.execute("end")
        iface = s.simulation.topology.devices["sw1"].interfaces["Gi0/1"]
        assert iface.switchport_mode == "access"

    def test_trunk_native_vlan(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("interface Gi0/1")
        s.execute("switchport mode trunk")
        s.execute("switchport trunk native vlan 10")
        s.execute("end")
        iface = s.simulation.topology.devices["sw1"].interfaces["Gi0/1"]
        assert iface.trunk_native_vlan == 10

    def test_trunk_allowed_vlan_set(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("vlan 20")
        s.execute("exit")
        s.execute("interface Gi0/1")
        s.execute("switchport mode trunk")
        s.execute("switchport trunk allowed vlan 1,10,20")
        s.execute("end")
        iface = s.simulation.topology.devices["sw1"].interfaces["Gi0/1"]
        assert iface.trunk_allowed_vlans == [1, 10, 20]

    def test_trunk_allowed_vlan_range(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        for v in range(10, 15):
            s.execute(f"vlan {v}")
            s.execute("exit")
        s.execute("interface Gi0/1")
        s.execute("switchport mode trunk")
        s.execute("switchport trunk allowed vlan 10-14")
        s.execute("end")
        iface = s.simulation.topology.devices["sw1"].interfaces["Gi0/1"]
        assert iface.trunk_allowed_vlans == [10, 11, 12, 13, 14]

    def test_trunk_allowed_vlan_add(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("vlan 20")
        s.execute("exit")
        s.execute("interface Gi0/1")
        s.execute("switchport mode trunk")
        s.execute("switchport trunk allowed vlan 1,10")
        s.execute("switchport trunk allowed vlan add 20")
        s.execute("end")
        iface = s.simulation.topology.devices["sw1"].interfaces["Gi0/1"]
        assert 20 in iface.trunk_allowed_vlans

    def test_trunk_allowed_vlan_remove(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("vlan 10")
        s.execute("exit")
        s.execute("interface Gi0/1")
        s.execute("switchport mode trunk")
        s.execute("switchport trunk allowed vlan 1,10")
        s.execute("switchport trunk allowed vlan remove 10")
        s.execute("end")
        iface = s.simulation.topology.devices["sw1"].interfaces["Gi0/1"]
        assert 10 not in (iface.trunk_allowed_vlans or [])

    def test_show_interfaces_trunk(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/1")
        s.execute("switchport mode trunk")
        s.execute("end")
        out = s.execute("show interfaces trunk")
        assert "Gi0/1" in out
        assert "trunking" in out

    def test_show_interfaces_status(self) -> None:
        s = make_switch_session("sw1")
        out = s.execute("show interfaces status")
        assert "Gi0/0" in out
        assert "connected" in out

    def test_no_trunk_shown_when_no_trunks(self) -> None:
        s = make_switch_session("sw1")
        out = s.execute("show interfaces trunk")
        assert "No trunk" in out or "%" in out


# ── EtherChannel CLI ──────────────────────────────────────────────────────────


class TestEtherChannelCLI:
    def test_channel_group_on(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/2")
        s.execute("channel-group 1 mode on")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        assert 1 in switch.port_channels
        assert "Gi0/2" in switch.port_channels[1].members

    def test_channel_group_lacp_active(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/2")
        s.execute("channel-group 1 mode active")
        s.execute("exit")  # back to global config
        s.execute("interface Gi0/3")
        s.execute("channel-group 1 mode active")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        pc = switch.port_channels[1]
        assert pc.protocol == "active"
        assert "Gi0/2" in pc.members
        assert "Gi0/3" in pc.members

    def test_channel_group_lacp_passive(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/2")
        s.execute("channel-group 1 mode passive")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        assert switch.port_channels[1].protocol == "passive"

    def test_channel_group_pagp_desirable(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/2")
        s.execute("channel-group 1 mode desirable")
        s.execute("end")
        switch = s.simulation.get_switch("sw1")
        assert switch.port_channels[1].protocol == "desirable"

    def test_show_etherchannel_summary(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/2")
        s.execute("channel-group 1 mode active")
        s.execute("end")
        out = s.execute("show etherchannel summary")
        assert "Port-channel1" in out
        assert "Gi0/2" in out

    def test_show_etherchannel_detail(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/2")
        s.execute("channel-group 1 mode active")
        s.execute("end")
        out = s.execute("show etherchannel detail")
        assert "Port-channel1" in out
        assert "LACP" in out

    def test_invalid_channel_group_id(self) -> None:
        s = make_switch_session("sw1")
        s.execute("configure terminal")
        s.execute("interface Gi0/2")
        out = s.execute("channel-group 99 mode on")
        assert "%" in out  # 99 out of range

    def test_load_balancing_deterministic(self) -> None:
        """EtherChannel load-balancing is deterministic for same src/dst."""
        from simulator_core.devices.switch import PortChannelGroup
        pc = PortChannelGroup(1)
        pc.add_member("Gi0/2")
        pc.add_member("Gi0/3")
        result1 = pc.select_egress("aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66")
        result2 = pc.select_egress("aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66")
        assert result1 == result2  # deterministic

    def test_load_balancing_different_flows(self) -> None:
        """Different src/dst pairs can go to different members."""
        from simulator_core.devices.switch import PortChannelGroup
        pc = PortChannelGroup(1)
        pc.add_member("Gi0/2")
        pc.add_member("Gi0/3")
        results = set()
        for i in range(20):
            mac = f"aa:bb:cc:dd:ee:{i:02x}"
            results.add(pc.select_egress(mac, "11:22:33:44:55:66"))
        # With 20 different MACs, both members should be used
        assert len(results) == 2


# ── VLAN list formatting ──────────────────────────────────────────────────────


class TestVLANListFormat:
    def test_format_contiguous(self) -> None:
        from simulator_core.cli import CLISession
        from tests.scenarios import build_sim
        sim = build_sim()
        s = CLISession(device_id="switch-1", simulation=sim)
        assert s._format_vlan_list([1, 2, 3, 4, 5]) == "1-5"

    def test_format_mixed(self) -> None:
        from simulator_core.cli import CLISession
        from tests.scenarios import build_sim
        sim = build_sim()
        s = CLISession(device_id="switch-1", simulation=sim)
        assert s._format_vlan_list([1, 10, 11, 12, 20]) == "1,10-12,20"

    def test_format_empty(self) -> None:
        from simulator_core.cli import CLISession
        from tests.scenarios import build_sim
        sim = build_sim()
        s = CLISession(device_id="switch-1", simulation=sim)
        assert s._format_vlan_list([]) == "none"

    def test_parse_range(self) -> None:
        from simulator_core.cli import CLISession
        from tests.scenarios import build_sim
        sim = build_sim()
        s = CLISession(device_id="switch-1", simulation=sim)
        result = s._parse_vlan_list("1,10-12,20")
        assert result == [1, 10, 11, 12, 20]

    def test_parse_all(self) -> None:
        from simulator_core.cli import CLISession
        from tests.scenarios import build_sim
        sim = build_sim()
        s = CLISession(device_id="switch-1", simulation=sim)
        result = s._parse_vlan_list("all")
        assert result is None
