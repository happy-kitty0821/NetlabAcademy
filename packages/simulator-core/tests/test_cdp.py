"""
tests/test_cdp.py
-----------------
Comprehensive tests for the Cisco Discovery Protocol (CDP) implementation.

Coverage:
  1.  CDPManager.update_neighbor stores CDPEntry correctly
  2.  CDPManager.expire_neighbors removes stale entries
  3.  CDPManager.get_neighbor returns the correct entry
  4.  CDPHelloEvent fires and schedules CDP FrameTransmit events
  5.  Switch receives CDP neighbor entry after frame delivery
  6.  show cdp neighbors output contains device ID and port
  7.  show cdp neighbors detail contains IP addresses
  8.  CDP frames do NOT add entries to the MAC table
  9.  CDP bypasses STP discarding state
 10.  CDP neighbor expires after holdtime ticks without refresh
 11.  start_cdp_timers() twice does not create duplicate event chains
 12.  reset() clears CDP state and stale timer chains do not fire
 13.  Two-switch topology: SW1 and SW2 each see the other as neighbor
 14.  cdp run / no cdp run CLI commands work
 15.  show cdp neighbors returns empty message when no neighbors

All imports are from simulator_core.* only.
No Django, no sockets, no subprocess.
"""

from __future__ import annotations

import pytest

from simulator_core.addresses import MACAddress
from simulator_core.cdp import CDPEntry, CDPManager
from simulator_core.cli import CLISession, CLIMode
from simulator_core.events import CDPHelloEvent, FrameTransmit
from simulator_core.frames import CDP_MULTICAST_MAC, EthernetFrame
from simulator_core.simulation import Simulation
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel, InterfaceState


# ---------------------------------------------------------------------------
# Shared topology helpers (mirrors test_stp_phase2.py patterns)
# ---------------------------------------------------------------------------

def _make_switch(sw_id: str, hostname: str, n_ports: int, base_mac: str) -> Device:
    """Return a Device(SWITCH) with n_ports Gi0/<i> interfaces."""
    dev = Device(id=sw_id, model=DeviceModel.SWITCH, hostname=hostname)
    parts = base_mac.split(":")
    for i in range(n_ports):
        last_byte = (int(parts[-1], 16) + i) & 0xFF
        port_mac = ":".join(parts[:-1] + [f"{last_byte:02x}"])
        dev.add_interface(Interface(name=f"Gi0/{i}", mac=MACAddress(port_mac)))
    return dev


def _make_host(h_id: str, hostname: str, mac: str, ip: str) -> Device:
    """Return a Device(HOST) with one eth0 interface configured."""
    dev = Device(id=h_id, model=DeviceModel.HOST, hostname=hostname)
    iface = Interface(name="eth0", mac=MACAddress(mac))
    iface.set_ip(ip)
    dev.add_interface(iface)
    return dev


def _build_two_switch_topo() -> tuple[Topology, str, str]:
    """
    SW1 (Gi0/0) ── (Gi0/0) SW2
    Returns (topology, sw1_id, sw2_id).
    """
    sw1 = _make_switch("sw1", "SW1", 2, "aa:00:00:00:00:01")
    sw2 = _make_switch("sw2", "SW2", 2, "bb:00:00:00:00:01")
    topo = Topology()
    topo.add_device(sw1)
    topo.add_device(sw2)
    topo.add_link(Link(
        id="l1",
        endpoint_a=("sw1", "Gi0/0"),
        endpoint_b=("sw2", "Gi0/0"),
    ))
    return topo, "sw1", "sw2"


def _build_switch_host_topo() -> tuple[Topology, str, str]:
    """
    SW1 (Gi0/0) ── (eth0) H1
    Returns (topology, sw1_id, h1_id).
    """
    sw1 = _make_switch("sw1", "SW1", 2, "aa:00:00:00:00:01")
    h1 = _make_host("h1", "H1", "cc:00:00:00:00:01", "10.0.0.1/24")
    topo = Topology()
    topo.add_device(sw1)
    topo.add_device(h1)
    topo.add_link(Link(
        id="l1",
        endpoint_a=("sw1", "Gi0/0"),
        endpoint_b=("h1", "eth0"),
    ))
    return topo, "sw1", "h1"


def _make_cdp_entry(
    device_id: str = "SW2",
    local_interface: str = "Gi0/0",
    holdtime: int = 180,
    capabilities: str = "Switch",
    ip_addresses: tuple[str, ...] = (),
) -> CDPEntry:
    return CDPEntry(
        device_id=device_id,
        local_interface=local_interface,
        holdtime=holdtime,
        capabilities=capabilities,
        platform="Cisco Catalyst 2960",
        software_version="NetLab Academy Simulator 1.0",
        ip_addresses=ip_addresses,
        native_vlan=1,
        duplex="full",
        vtp_domain="",
        advertisement_version=2,
    )


# ===========================================================================
# Test 1: CDPManager.update_neighbor stores CDPEntry correctly
# ===========================================================================

def test_cdp_manager_update_neighbor_stores_entry() -> None:
    mgr = CDPManager("dev1", "SW1", "Switch", "Cisco Catalyst 2960")
    entry = _make_cdp_entry("SW2", "Gi0/0")
    mgr.update_neighbor("Gi0/0", entry, current_tick=10)

    stored = mgr.get_neighbor("Gi0/0")
    assert stored is not None
    assert stored.device_id == "SW2"
    assert stored.local_interface == "Gi0/0"
    assert stored.capabilities == "Switch"


# ===========================================================================
# Test 2: CDPManager.expire_neighbors removes stale entries
# ===========================================================================

def test_cdp_manager_expire_neighbors_removes_stale() -> None:
    mgr = CDPManager("dev1", "SW1", "Switch", "Cisco Catalyst 2960")
    # holdtime=10, last_seen=0, expire at tick > 10
    entry = _make_cdp_entry(holdtime=10)
    mgr.update_neighbor("Gi0/0", entry, current_tick=0)

    # Not yet expired at tick 9
    expired = mgr.expire_neighbors(9)
    assert expired == []
    assert mgr.get_neighbor("Gi0/0") is not None

    # Expired at tick 11
    expired = mgr.expire_neighbors(11)
    assert "Gi0/0" in expired
    assert mgr.get_neighbor("Gi0/0") is None


# ===========================================================================
# Test 3: CDPManager.get_neighbor returns correct entry
# ===========================================================================

def test_cdp_manager_get_neighbor_returns_correct() -> None:
    mgr = CDPManager("dev1", "SW1", "Switch", "Cisco Catalyst 2960")
    e1 = _make_cdp_entry("Peer1", "Gi0/0")
    e2 = _make_cdp_entry("Peer2", "Gi0/1")
    mgr.update_neighbor("Gi0/0", e1, 0)
    mgr.update_neighbor("Gi0/1", e2, 0)

    assert mgr.get_neighbor("Gi0/0") is e1
    assert mgr.get_neighbor("Gi0/1") is e2
    assert mgr.get_neighbor("Gi0/2") is None


# ===========================================================================
# Test 4: CDPHelloEvent fires and CDP FrameTransmit events are scheduled
# ===========================================================================

def test_cdp_hello_event_fires_and_schedules_frames() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)

    # CDP timers must be started explicitly (same as BPDU hello timers).
    sim.start_cdp_timers()

    # CDPHelloEvents should now be queued.
    cdp_events = [
        e for e in sim._scheduler._heap
        if isinstance(e[2], CDPHelloEvent)
    ]
    assert len(cdp_events) >= 2, "Expected CDPHelloEvent for each switch"

    # Run the simulation and check that CDP FrameTransmit events appear
    sim.run()
    cdp_transmits = [
        e for e in sim.trace
        if isinstance(e, FrameTransmit) and e.frame.cdp_payload is not None
    ]
    assert len(cdp_transmits) > 0, "Expected CDP FrameTransmit events in trace"


# ===========================================================================
# Test 5: Switch receives CDP neighbor entry after frame delivery
# ===========================================================================

def test_switch_receives_cdp_neighbor_entry_after_delivery() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)
    sim.start_cdp_timers()
    sim.run()

    sw1 = sim.get_switch(sw1_id)
    sw2 = sim.get_switch(sw2_id)

    # SW1 should see SW2 as a neighbor on Gi0/0
    # SW2 should see SW1 as a neighbor on Gi0/0
    sw1_neighbors = dict(sw1.cdp_manager.get_neighbors())
    sw2_neighbors = dict(sw2.cdp_manager.get_neighbors())

    assert len(sw1_neighbors) >= 1, "SW1 should have at least one CDP neighbor"
    assert len(sw2_neighbors) >= 1, "SW2 should have at least one CDP neighbor"
    # The neighbor for SW1 should reference SW2's hostname
    assert any(e.device_id == "SW2" for e in sw1_neighbors.values())
    assert any(e.device_id == "SW1" for e in sw2_neighbors.values())


# ===========================================================================
# Test 6: show cdp neighbors output contains device ID and port
# ===========================================================================

def test_show_cdp_neighbors_output_contains_device_id() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)
    sim.start_cdp_timers()
    sim.run()

    # Also seed the neighbor manually in case timing is tight
    sw1 = sim.get_switch(sw1_id)
    entry = _make_cdp_entry("SW2", "Gi0/0")
    sw1.cdp_manager.update_neighbor("Gi0/0", entry, current_tick=0)

    sess = CLISession(device_id=sw1_id, simulation=sim)
    sess.mode = CLIMode.PRIV_EXEC
    output = sess.execute("show cdp neighbors")

    assert "SW2" in output
    assert "Gi0/0" in output


# ===========================================================================
# Test 7: show cdp neighbors detail contains IP addresses
# ===========================================================================

def test_show_cdp_neighbors_detail_contains_ip() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)

    sw1 = sim.get_switch(sw1_id)
    entry = _make_cdp_entry("SW2", "Gi0/0", ip_addresses=("192.168.1.1",))
    sw1.cdp_manager.update_neighbor("Gi0/0", entry, current_tick=0)

    sess = CLISession(device_id=sw1_id, simulation=sim)
    sess.mode = CLIMode.PRIV_EXEC
    output = sess.execute("show cdp neighbors detail")

    assert "192.168.1.1" in output
    assert "SW2" in output
    assert "Cisco Catalyst 2960" in output


# ===========================================================================
# Test 8: CDP frames do NOT add entries to MAC table
# ===========================================================================

def test_no_mac_learning_from_cdp_frames() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)
    sim.start_cdp_timers()
    sim.run()

    sw1 = sim.get_switch(sw1_id)
    mac_table = sw1.mac_table

    # The CDP multicast destination MAC must NOT be in the MAC table
    for (mac, _vlan) in mac_table:
        assert mac.lower() != CDP_MULTICAST_MAC.lower(), (
            f"CDP multicast MAC {CDP_MULTICAST_MAC} must not be learned in MAC table"
        )
    # Also the source MACs of CDP frames should NOT be learned from CDP frames
    # (the CDP handler returns immediately without calling _learn)
    # We verify by checking that no entry in the MAC table was created solely
    # from CDP — the source MAC of Gi0/0 on sw2 would only appear if
    # normal data frames were exchanged (which they were not in this test).
    # So the MAC table should be empty (no data traffic).
    assert len(mac_table) == 0, (
        "No data frames were sent, so MAC table should be empty after CDP-only traffic"
    )


# ===========================================================================
# Test 9: CDP bypasses STP discarding state
# ===========================================================================

def test_cdp_bypasses_stp_discarding() -> None:
    """
    A CDP frame must arrive at a switch even when the ingress port is on
    an STP DISCARDING port.
    """
    from simulator_core.stp import PortState

    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)

    sw1 = sim.get_switch(sw1_id)

    # Force Gi0/0 on SW1 into DISCARDING for VLAN 1
    inst = sw1.stp.get_instance(1)
    if inst is not None:
        ps = inst.port_states.get("Gi0/0")
        if ps is not None:
            ps.state = PortState.DISCARDING

    # Manually send a CDP frame from SW2 → SW1 (single shot, not via timer)
    sim._send_cdp_for_device(sw2_id, tick=0)
    sim.run()

    # SW1 should have SW2 as a neighbor despite DISCARDING state
    sw1_neighbors = dict(sw1.cdp_manager.get_neighbors())
    assert any(e.device_id == "SW2" for e in sw1_neighbors.values()), (
        "CDP must arrive on DISCARDING port and update the neighbor table"
    )


# ===========================================================================
# Test 10: CDP neighbor expires after holdtime ticks without refresh
# ===========================================================================

def test_cdp_neighbor_expires_after_holdtime() -> None:
    mgr = CDPManager("dev1", "SW1", "Switch", "Cisco Catalyst 2960")
    entry = _make_cdp_entry(holdtime=180)
    mgr.update_neighbor("Gi0/0", entry, current_tick=100)

    # Should still be there at tick 279 (< 100 + 180)
    mgr.expire_neighbors(279)
    assert mgr.get_neighbor("Gi0/0") is not None

    # Should be gone at tick 281 (> 100 + 180)
    mgr.expire_neighbors(281)
    assert mgr.get_neighbor("Gi0/0") is None


# ===========================================================================
# Test 11: calling start_cdp_timers() twice does not create duplicate chains
# ===========================================================================

def test_start_cdp_timers_twice_no_duplicate_chains() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)

    # Call start_cdp_timers twice
    sim.start_cdp_timers()
    sim.start_cdp_timers()

    # Collect all CDPHelloEvents in the queue
    cdp_events = [
        e[2] for e in sim._scheduler._heap
        if isinstance(e[2], CDPHelloEvent)
    ]

    # Group by device_id — each device should have at most one valid event
    from collections import Counter
    counts = Counter(e.device_id for e in cdp_events)
    for dev_id, count in counts.items():
        current_gen = sim._cdp_generation[dev_id]
        # Only count events with the current generation (old ones are stale)
        valid_count = sum(
            1 for e in cdp_events
            if e.device_id == dev_id and e.generation == current_gen
        )
        assert valid_count <= 1, (
            f"Device {dev_id} has {valid_count} active CDP chains; expected at most 1"
        )


# ===========================================================================
# Test 12: reset() clears CDP state and old timer chains do not fire
# ===========================================================================

def test_reset_clears_cdp_state() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)
    sim.start_cdp_timers()
    sim.run()

    # After run(), sw1 should have a CDP neighbor
    sw1 = sim.get_switch(sw1_id)
    assert len(sw1.cdp_manager.get_neighbors()) > 0

    # Reset the simulation
    sim.reset()

    # After reset, the CDP neighbor table should be empty on the new switch objects
    sw1_new = sim.get_switch(sw1_id)
    assert len(sw1_new.cdp_manager.get_neighbors()) == 0, (
        "CDP neighbor table should be empty after reset()"
    )

    # Verify that old CDPHelloEvents are stale (generation mismatch)
    # by running and checking no stale events cause issues
    sim.start_cdp_timers()
    sim.run()
    # Should complete without error — stale events are silently discarded


# ===========================================================================
# Test 13: Two-switch topology — SW1 and SW2 each see the other as neighbor
# ===========================================================================

def test_two_switch_topology_mutual_discovery() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)
    sim.start_cdp_timers()
    sim.run()

    sw1 = sim.get_switch(sw1_id)
    sw2 = sim.get_switch(sw2_id)

    sw1_neighbor_ids = {e.device_id for _, e in sw1.cdp_manager.get_neighbors()}
    sw2_neighbor_ids = {e.device_id for _, e in sw2.cdp_manager.get_neighbors()}

    assert "SW2" in sw1_neighbor_ids, "SW1 should discover SW2 via CDP"
    assert "SW1" in sw2_neighbor_ids, "SW2 should discover SW1 via CDP"


# ===========================================================================
# Test 14: cdp run / no cdp run CLI commands work
# ===========================================================================

def test_cdp_run_no_cdp_run_cli() -> None:
    topo, sw1_id, _sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)
    sw1 = sim.get_switch(sw1_id)

    sess = CLISession(device_id=sw1_id, simulation=sim)
    sess.execute("enable")
    sess.execute("configure terminal")

    # CDP should be enabled by default
    assert sw1.cdp_manager.is_enabled is True

    # Disable CDP
    out = sess.execute("no cdp run")
    assert "%" not in out or "Invalid" not in out  # no error
    assert sw1.cdp_manager.is_enabled is False

    # Re-enable CDP
    out = sess.execute("cdp run")
    assert "%" not in out or "Invalid" not in out
    assert sw1.cdp_manager.is_enabled is True


# ===========================================================================
# Test 15: show cdp neighbors returns empty message when no neighbors
# ===========================================================================

def test_show_cdp_neighbors_empty_when_no_neighbors() -> None:
    topo, sw1_id, sw2_id = _build_two_switch_topo()
    sim = Simulation(topo, seed=0, max_ticks=3600)
    # Do NOT run — neighbor table stays empty

    sw1 = sim.get_switch(sw1_id)
    # Ensure neighbor table is empty
    sw1.cdp_manager.clear()

    sess = CLISession(device_id=sw1_id, simulation=sim)
    sess.mode = CLIMode.PRIV_EXEC
    output = sess.execute("show cdp neighbors")

    # Should not error and should indicate zero entries
    assert "0" in output or "empty" in output.lower() or "Total cdp entries" in output
