"""
simulator_core.devices.switch
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Ethernet switch device protocol logic.

Responsibilities:
- MAC address learning from arriving frames.
- Known-unicast forwarding.
- Unknown-unicast and broadcast flooding.
- Port-down drop detection on egress.

The switch operates on the default VLAN (1) for all ports in this PoC.
No 802.1Q trunking, no VLAN access/trunk mode, no STP.

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
    Protocol logic for a simulated Ethernet switch.

    One Switch instance exists per SWITCH-model Device in the Simulation.

    MAC address table
    -----------------
    Keyed by ``(mac_value: str, vlan: int)`` → interface_name.
    All ports are on VLAN 1 in this PoC.
    """

    def __init__(self, device: Device, simulation: "Simulation") -> None:
        self._device = device
        self._sim = simulation
        # (mac_value, vlan) → interface_name
        self._mac_table: dict[tuple[str, int], str] = {}

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

    # ------------------------------------------------------------------
    # FrameArrival handler
    # ------------------------------------------------------------------

    def handle_frame_arrival(self, event: FrameArrival) -> None:
        """
        Process a frame arriving on *event.interface_name*.

        Steps:
        1. Learn source MAC.
        2. Forward to destination:
           - Broadcast → flood all ports except ingress.
           - Known unicast → send on the learned port (if not ingress).
           - Unknown unicast → flood all ports except ingress.
        """
        frame = event.frame
        ingress_iface = event.interface_name
        vlan = DEFAULT_VLAN
        arrive_time = event.time

        # 1. Learn source MAC.
        self._learn(arrive_time, frame.src_mac.value, ingress_iface, vlan)

        # 2. Determine egress port(s).
        dst_mac = frame.dst_mac.value

        if frame.dst_mac.is_broadcast:
            # Flood on all ports except ingress.
            self._flood(arrive_time, frame, ingress_iface, vlan)
        else:
            known_port = self._mac_table.get((dst_mac, vlan))
            if known_port is not None and known_port != ingress_iface:
                # Known unicast — forward on the single learned port.
                self._forward(arrive_time, frame, known_port)
            elif known_port == ingress_iface:
                # Destination is on the same port as source — drop (no loop).
                pass
            else:
                # Unknown unicast — flood.
                self._flood(arrive_time, frame, ingress_iface, vlan)

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
            return  # interface not on this switch — should not happen

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

    def _flood(
        self,
        time: int,
        frame: EthernetFrame,
        ingress_iface: str,
        vlan: int,
    ) -> None:
        """Transmit *frame* on every port except *ingress_iface*."""
        for iface_name in self._device.interfaces:
            if iface_name == ingress_iface:
                continue
            self._forward(time, frame, iface_name)
