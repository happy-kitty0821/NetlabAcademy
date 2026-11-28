"""
Native VLAN consistency across switch links (CDP's NATIVE_VLAN_MISMATCH).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simulator_core.types import InterfaceState

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


def log_native_vlan_mismatches(sim: "Simulation") -> None:
    """
    CDP on IOS compares the native VLAN at both ends of a link and logs
    ``%CDP-4-NATIVE_VLAN_MISMATCH`` on each switch.  A trunk's native
    VLAN is its untagged VLAN; an access port's is its access VLAN.

    Logged once when a mismatch appears (IOS repeats it every minute
    while it lasts); fixing either end clears it.
    """
    from simulator_core.naming import long_name
    current: set[tuple] = set()
    for link in sim._topology.links:
        (da, ia), (db, ib) = link.endpoint_a, link.endpoint_b
        ends = []
        for dev_id, name in ((da, ia), (db, ib)):
            if dev_id not in sim._switches:
                break
            iface = sim._topology.devices[dev_id].interfaces.get(name)
            cdp = sim._get_cdp_manager(dev_id)
            if (iface is None or iface.oper_state != InterfaceState.UP
                    or cdp is None or not cdp.is_enabled
                    or not getattr(iface, "_cdp_enabled", True)):
                break
            native = iface.trunk_native_vlan if iface.is_trunk else iface.vlan
            ends.append((dev_id, name, native))
        if len(ends) != 2 or ends[0][2] == ends[1][2]:
            continue
        key = (link.id, ends[0][2], ends[1][2])
        current.add(key)
        if key in sim._native_mismatches:
            continue
        for (dev_id, name, native), (peer_id, peer_name, peer_native) in (
                (ends[0], ends[1]), (ends[1], ends[0])):
            peer_host = sim._topology.devices[peer_id].hostname
            sim.log_event(
                dev_id, "CDP", 4, "NATIVE_VLAN_MISMATCH",
                f"Native VLAN mismatch discovered on {long_name(name)} ({native}), "
                f"with {peer_host} {long_name(peer_name)} ({peer_native}).",
            )
    sim._native_mismatches = current
