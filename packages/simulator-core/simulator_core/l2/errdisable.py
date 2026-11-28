"""
Err-disable: putting ports in the err-disabled state, BPDU guard and
errdisable recovery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simulator_core.types import InterfaceState

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


def err_disable(sim: "Simulation", device_id: str, iface_name: str, cause: str) -> bool:
    """
    Put a port in the err-disabled state (it goes down until "shutdown /
    no shutdown" or errdisable recovery).  Returns False if it already was.
    The caller refreshes interface states.
    """
    device = sim._topology.devices.get(device_id)
    iface = device.interfaces.get(iface_name) if device else None
    if iface is None or iface.err_disabled:
        return False
    iface.err_disabled = cause
    iface.err_disabled_at = sim._lab_time
    sim.log_event(device_id, "PM", 4, "ERR_DISABLE",
                   f"{cause} error detected on {iface_name}, putting {iface_name} "
                   f"in err-disable state")
    return True


def bpdu_guard_trip(sim: "Simulation", device_id: str, iface_name: str) -> None:
    """A BPDU arrived on a port with BPDU guard: disable it."""
    device = sim._topology.devices.get(device_id)
    iface = device.interfaces.get(iface_name) if device else None
    if iface is None or iface.err_disabled:
        return
    sim.log_event(device_id, "SPANTREE", 2, "BLOCK_BPDUGUARD",
                   f"Received BPDU on port {iface_name} with BPDU Guard enabled. "
                   f"Disabling port.")
    err_disable(sim, device_id, iface_name, "bpduguard")


def apply_bpdu_guard(sim: "Simulation") -> bool:
    """
    Spanning tree is computed directly, not from BPDU frames, so BPDU
    guard is checked here: a guarded port that is up and cabled to a
    switch port sending BPDUs is err-disabled.  Returns True if any was.
    """
    tripped = False
    for dev_id, switch in sim._switches.items():
        device = sim._topology.devices[dev_id]
        for name, iface in device.interfaces.items():
            if (not iface.is_physical_switchport or iface.err_disabled
                    or iface.oper_state != InterfaceState.UP
                    or not switch.bpdu_guard_enabled(name)):
                continue
            peer = sim._topology.neighbours(dev_id, name)
            peer_switch = sim._switches.get(peer[0]) if peer else None
            if peer_switch is None or not peer_switch.sends_bpdus(peer[1]):
                continue
            bpdu_guard_trip(sim, dev_id, name)
            tripped = True
    return tripped


def recover_err_disabled(sim: "Simulation") -> None:
    """errdisable recovery: re-enable ports whose timer has expired."""
    recovered = False
    for dev_id, switch in sim._switches.items():
        for name, iface in sim._topology.devices[dev_id].interfaces.items():
            cause = iface.err_disabled
            if (cause and cause in switch.errdisable_recovery
                    and sim._lab_time - iface.err_disabled_at >= switch.errdisable_interval):
                sim.log_event(dev_id, "PM", 4, "ERR_RECOVER",
                               f"Attempting to recover from {cause} err-disable state "
                               f"on {name}")
                iface.err_disabled = None
                recovered = True
    if recovered:
        # The cause may still be there (a BPDU-sending switch on a
        # guarded port): the refresh disables the port again, as on IOS.
        sim.refresh_interface_states()
