"""
simulator_core.devices.switch
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ethernet switch with VLAN support.

Responsibilities:
- VLAN database (create, name, delete VLANs).
- MAC address learning per VLAN.
- Known-unicast forwarding within the same VLAN.
- Unknown-unicast and broadcast flooding within the same VLAN.
- Port-down drop detection on egress.
- Access port VLAN assignment (802.1Q trunking is a future feature).

No host I/O, no socket imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simulator_core.events import (
    FrameArrival,
    FrameDropped,
    FrameTransmit,
    MACTableLearned,
    DROP_PORT_DOWN,
)
from simulator_core.frames import EthernetFrame
from simulator_core.topology import Device
from simulator_core.types import DEFAULT_VLAN, InterfaceState

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


class Switch:
    """
    Protocol logic for a simulated Ethernet switch with VLAN support.

    VLAN database
    -------------
    ``vlans`` is a dict mapping VLAN ID (int) → VLAN name (str).
    VLAN 1 ("default") always exists.

    Access port VLAN assignment
    ---------------------------
    Each interface has a ``vlan`` field (default 1).  When a frame
    arrives on an access port, its VLAN is determined by the interface's
    VLAN assignment.  Forwarding and flooding only consider ports in the
    same VLAN.

    MAC address table
    -----------------
    Keyed by ``(mac_value, vlan)`` → interface_name.  MACs are learned
    per-VLAN so the same MAC can appear on different VLANs on different
    ports.
    """

    def __init__(self, device: Device, simulation: "Simulation") -> None:
        self._device = device
        self._sim = simulation
        # (mac_value, vlan) → interface_name
        self._mac_table: dict[tuple[str, int], str] = {}
        # VLAN database: vlan_id → vlan_name
        self._vlans: dict[int, str] = {1: "default"}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_id(self) -> str:
        return self._device.id

    @property
    def mac_table(self) -> dict[tuple[str, int], str]:
        """Read-only view of the MAC address table."""
        return dict(self._mac_table)

    @property
    def vlans(self) -> dict[int, str]:
        """Read-only view of the VLAN database."""
        return dict(self._vlans)

    # ------------------------------------------------------------------
    # VLAN management (called by CLI)
    # ------------------------------------------------------------------

    def create_vlan(self, vlan_id: int, name: str = "") -> None:
        """Create a VLAN.  Raises ValueError if VLAN ID is out of range."""
        if not (1 <= vlan_id <= 4094):
            raise ValueError(f"VLAN ID must be 1-4094, got {vlan_id}")
        if vlan_id not in self._vlans:
            self._vlans[vlan_id] = name or f"VLAN{vlan_id:04d}"

    def name_vlan(self, vlan_id: int, name: str) -> None:
        """Set the name of an existing VLAN."""
        if vlan_id not in self._vlans:
            raise ValueError(f"VLAN {vlan_id} does not exist")
        self._vlans[vlan_id] = name

    def delete_vlan(self, vlan_id: int) -> None:
        """Delete a VLAN.  VLAN 1 cannot be deleted."""
        if vlan_id == 1:
            raise ValueError("Default VLAN 1 cannot be deleted")
        if vlan_id not in self._vlans:
            raise ValueError(f"VLAN {vlan_id} does not exist")
        del self._vlans[vlan_id]
        # Reset any ports assigned to this VLAN back to VLAN 1
        for iface in self._device.interfaces.values():
            if iface.vlan == vlan_id:
                iface.vlan = 1

    def set_port_vlan(self, iface_name: str, vlan_id: int) -> None:
        """Assign an access port to a VLAN."""
        if vlan_id not in self._vlans:
            raise ValueError(f"VLAN {vlan_id} does not exist. Create it first.")
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            raise ValueError(f"Interface {iface_name!r} not found")
        iface.vlan = vlan_id

    def get_port_vlan(self, iface_name: str) -> int:
        """Return the VLAN ID assigned to a port."""
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            return DEFAULT_VLAN
        return iface.vlan

    def ports_in_vlan(self, vlan_id: int) -> list[str]:
        """Return list of interface names assigned to the given VLAN."""
        return [
            name for name, iface in self._device.interfaces.items()
            if iface.vlan == vlan_id
        ]

    # ------------------------------------------------------------------
    # FrameArrival handler
    # ------------------------------------------------------------------

    def handle_frame_arrival(self, event: FrameArrival) -> None:
        """
        Process a frame arriving on *event.interface_name*.

        Steps:
        1. Determine the VLAN from the ingress port's VLAN assignment.
        2. Learn source MAC in that VLAN.
        3. Forward within the same VLAN only:
           - Broadcast → flood all ports in the same VLAN except ingress.
           - Known unicast → forward on the learned port (if same VLAN).
           - Unknown unicast → flood within the same VLAN.
        """
        frame = event.frame
        ingress_iface = event.interface_name
        arrive_time = event.time

        # Determine VLAN from the ingress port
        vlan = self.get_port_vlan(ingress_iface)

        # 1. Learn source MAC in this VLAN.
        self._learn(arrive_time, frame.src_mac.value, ingress_iface, vlan)

        # 2. Determine egress port(s).
        dst_mac = frame.dst_mac.value

        if frame.dst_mac.is_broadcast:
            self._flood_in_vlan(arrive_time, frame, ingress_iface, vlan)
        else:
            known_port = self._mac_table.get((dst_mac, vlan))
            if known_port is not None and known_port != ingress_iface:
                # Known unicast — forward only if the destination port is
                # in the same VLAN.
                if self.get_port_vlan(known_port) == vlan:
                    self._forward(arrive_time, frame, known_port)
                else:
                    # Destination MAC is on a different VLAN — drop.
                    pass
            elif known_port == ingress_iface:
                # Destination is on the same port — drop.
                pass
            else:
                # Unknown unicast — flood within the same VLAN.
                self._flood_in_vlan(arrive_time, frame, ingress_iface, vlan)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _learn(self, time: int, mac_value: str, iface_name: str, vlan: int) -> None:
        """Record (mac, vlan) → iface_name if not already known."""
        key = (mac_value, vlan)
        if self._mac_table.get(key) != iface_name:
            self._mac_table[key] = iface_name
            seq = self._sim.next_seq()
            evt = MACTableLearned(
                time=time, seq=seq,
                switch_id=self.device_id,
                mac_address=mac_value,
                interface_name=iface_name,
                vlan=vlan,
            )
            self._sim.schedule(evt)

    def _forward(self, time: int, frame: EthernetFrame, egress_iface: str) -> None:
        """Transmit *frame* on *egress_iface*, checking port state first."""
        iface = self._device.interfaces.get(egress_iface)
        if iface is None:
            return

        if iface.admin_state == InterfaceState.DOWN:
            seq = self._sim.next_seq()
            drop = FrameDropped(
                time=time + 1, seq=seq,
                device_id=self.device_id,
                interface_name=egress_iface,
                frame=frame,
                reason=DROP_PORT_DOWN,
            )
            self._sim._record(drop)
            return

        seq = self._sim.next_seq()
        tx = FrameTransmit(
            time=time + 1, seq=seq,
            device_id=self.device_id,
            interface_name=egress_iface,
            frame=frame,
        )
        self._sim.schedule(tx)

    def _flood_in_vlan(
        self,
        time: int,
        frame: EthernetFrame,
        ingress_iface: str,
        vlan: int,
    ) -> None:
        """Transmit *frame* on every port in *vlan* except *ingress_iface*."""
        for iface_name, iface in self._device.interfaces.items():
            if iface_name == ingress_iface:
                continue
            # Only flood to ports in the same VLAN
            if iface.vlan != vlan:
                continue
            self._forward(time, frame, iface_name)
