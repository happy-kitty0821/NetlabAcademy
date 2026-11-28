"""
DTP (Dynamic Trunking Protocol): settling dynamic ports as trunk or access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simulator_core.types import InterfaceState

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


def negotiate_dtp(sim: "Simulation") -> None:
    """
    Settle every dynamic switchport as a trunk or an access port.

    IOS rules, by the two ends' administrative modes:

    ===================  =====  =====  =========  =====  ==================
    local vs peer        auto   desir  trunk      access trunk+nonegotiate
    ===================  =====  =====  =========  =====  ==================
    dynamic auto         acc    trunk  trunk      acc    acc
    dynamic desirable    trunk  trunk  trunk      acc    acc
    ===================  =====  =====  =========  =====  ==================

    A port that is down, or cabled to anything but a switchport (a
    router, a PC), runs as access: nobody answers its DTP frames.
    """
    from simulator_core.types import DeviceModel
    for device in sim._topology.devices.values():
        if device.model != DeviceModel.SWITCH:
            continue
        for name, iface in device.interfaces.items():
            if not iface.switchport_mode.startswith("dynamic_"):
                iface.dtp_trunking = False
                continue
            peer = dtp_peer(sim, device.id, name, iface)
            iface.dtp_trunking = peer is not None and dtp_forms_trunk(iface, peer)


def dtp_peer(sim: "Simulation", device_id: str, name: str, iface):
    """The switchport across an up link from *iface*, or None."""
    from simulator_core.types import DeviceModel
    if not iface.is_physical_switchport or iface.oper_state != InterfaceState.UP:
        return None
    peer = sim._topology.neighbours(device_id, name)
    if peer is None:
        return None
    peer_dev = sim._topology.devices.get(peer[0])
    if peer_dev is None or peer_dev.model != DeviceModel.SWITCH:
        return None
    peer_iface = peer_dev.interfaces.get(peer[1])
    if peer_iface is None or not peer_iface.is_physical_switchport:
        return None
    return peer_iface


def dtp_forms_trunk(local, peer) -> bool:
    """
    Does dynamic port *local* become a trunk with *peer*?  Only a peer that
    sends DTP frames (not access, not ``nonegotiate``) can bring it up, and
    two ``dynamic auto`` ports both wait for the other, so they stay access.
    """
    if peer.dtp_nonegotiate:
        return False
    if peer.switchport_mode in ("trunk", "dynamic_desirable"):
        return True
    if peer.switchport_mode == "dynamic_auto":
        return local.switchport_mode == "dynamic_desirable"
    return False
