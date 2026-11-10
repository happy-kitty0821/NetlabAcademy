"""
simulator_core.devices.router
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Router device — IPv4 packet forwarding.

Responsibilities:
- Maintain a routing table (connected + static routes).
- On IPv4 FrameArrival: look up destination, decrement TTL, forward.
- ARP resolution for next-hop on egress interface.
- ICMP time-exceeded when TTL hits 0.
- ICMP destination unreachable when no route exists.
- CLI: ip route, show ip route.

No host I/O, no sockets, no subprocess.
"""

from __future__ import annotations

import uuid
from ipaddress import IPv4Address, IPv4Network
from typing import TYPE_CHECKING, Optional

from simulator_core.addresses import BROADCAST_MAC, MACAddress, ZERO_MAC
from simulator_core.events import (
    ARPRequestSent,
    ARPReplySent,
    FrameArrival,
    FrameDropped,
    FrameTransmit,
    DROP_NO_ROUTE,
    DROP_TTL_EXCEEDED,
)
from simulator_core.frames import (
    ARPMessage,
    EthernetFrame,
    ICMPMessage,
    IPv4Packet,
)
from simulator_core.routing import RoutingTable, RouteSource
from simulator_core.topology import Device
from simulator_core.types import InterfaceState

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


class Router:
    """
    Protocol logic for a simulated IPv4 router.

    One Router instance exists per ROUTER-model Device in the Simulation.
    """

    def __init__(self, device: Device, simulation: "Simulation") -> None:
        self._device = device
        self._sim = simulation

        # Routing table
        self._routing_table = RoutingTable()

        # ARP cache: IPv4Address → MACAddress
        self._arp_cache: dict[IPv4Address, MACAddress] = {}

        # Pending packets awaiting ARP resolution:
        # dst_ip → list of (packet, ingress_interface)
        self._pending_arp: dict[IPv4Address, list[tuple[IPv4Packet, str]]] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_id(self) -> str:
        return self._device.id

    @property
    def routing_table(self) -> RoutingTable:
        return self._routing_table

    @property
    def arp_cache(self) -> dict[IPv4Address, MACAddress]:
        return dict(self._arp_cache)

    # ------------------------------------------------------------------
    # Route management (called by simulation on interface change)
    # ------------------------------------------------------------------

    def update_connected_routes(self) -> None:
        """
        Rebuild connected routes from all interfaces that have an IP address
        and are in the UP state.
        """
        # Remove all existing connected routes
        self._routing_table._routes = [
            r for r in self._routing_table._routes
            if r.source != RouteSource.CONNECTED
        ]

        from simulator_core.types import InterfaceState
        for name, iface in self._device.interfaces.items():
            if iface.ip_config and iface.admin_state == InterfaceState.UP:
                net = iface.ip_config.network
                self._routing_table.add_connected_route(net, name)

    # ------------------------------------------------------------------
    # FrameArrival handler
    # ------------------------------------------------------------------

    def handle_frame_arrival(self, event: FrameArrival) -> None:
        """Process a frame arriving at the router."""
        frame = event.frame

        if frame.ethertype == EthernetFrame.ETHERTYPE_ARP:
            # Router participates in ARP for its own interfaces
            from simulator_core.frames import ARPMessage
            assert isinstance(frame.payload, ARPMessage)
            self._handle_arp(event, frame.payload)

        elif frame.ethertype == EthernetFrame.ETHERTYPE_IPV4:
            assert isinstance(frame.payload, IPv4Packet)
            self._handle_ipv4(event, frame.payload)

    # ------------------------------------------------------------------
    # ARP
    # ------------------------------------------------------------------

    def _handle_arp(self, event: FrameArrival, arp: ARPMessage) -> None:
        """Process ARP request/reply."""
        # Find the interface the ARP came in on
        iface_name = event.interface_name
        iface = self._device.interfaces.get(iface_name)
        if iface is None or iface.ip_config is None:
            return

        own_ip = iface.ip_config.address

        # Learn sender mapping
        self._arp_cache[arp.sender_ip] = arp.sender_mac

        if arp.operation == ARPMessage.ARP_REQUEST and arp.target_ip == own_ip:
            # Reply to ARP request for our IP
            self._send_arp_reply(event, arp, iface)

        elif arp.operation == ARPMessage.ARP_REPLY:
            # Unblock pending packets
            self._unblock_pending(arp.sender_ip, arp.sender_mac)

    def _send_arp_reply(self, event: FrameArrival, request: ARPMessage, iface) -> None:
        own_mac = iface.mac
        own_ip = iface.ip_config.address
        t = event.time + 1

        reply = ARPMessage(
            operation=ARPMessage.ARP_REPLY,
            sender_mac=own_mac,
            sender_ip=own_ip,
            target_mac=request.sender_mac,
            target_ip=request.sender_ip,
        )
        frame = EthernetFrame(
            src_mac=own_mac,
            dst_mac=request.sender_mac,
            ethertype=EthernetFrame.ETHERTYPE_ARP,
            payload=reply,
            frame_id=str(uuid.uuid4()),
        )

        seq_reply = self._sim.next_seq()
        self._sim.schedule(ARPReplySent(
            time=t, seq=seq_reply,
            device_id=self.device_id,
            message=reply,
        ))

        seq_tx = self._sim.next_seq()
        self._sim.schedule(FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=iface.name,
            frame=frame,
        ))

    def _send_arp_request(self, target_ip: IPv4Address, iface_name: str) -> None:
        """Send an ARP request for target_ip out of iface_name."""
        iface = self._device.interfaces.get(iface_name)
        if iface is None or iface.ip_config is None:
            return

        own_mac = iface.mac
        own_ip = iface.ip_config.address
        t = self._sim.clock + 1

        arp_msg = ARPMessage(
            operation=ARPMessage.ARP_REQUEST,
            sender_mac=own_mac,
            sender_ip=own_ip,
            target_mac=ZERO_MAC,
            target_ip=target_ip,
        )
        frame = EthernetFrame(
            src_mac=own_mac,
            dst_mac=BROADCAST_MAC,
            ethertype=EthernetFrame.ETHERTYPE_ARP,
            payload=arp_msg,
            frame_id=str(uuid.uuid4()),
        )

        seq_req = self._sim.next_seq()
        self._sim.schedule(ARPRequestSent(
            time=t, seq=seq_req,
            device_id=self.device_id,
            message=arp_msg,
        ))

        seq_tx = self._sim.next_seq()
        self._sim.schedule(FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=iface_name,
            frame=frame,
        ))

    def _unblock_pending(self, ip: IPv4Address, mac: MACAddress) -> None:
        """ARP reply received — forward pending packets."""
        pending = self._pending_arp.pop(ip, [])
        for pkt, iface_name in pending:
            self._forward_packet(pkt, mac, iface_name)

    # ------------------------------------------------------------------
    # IPv4 forwarding
    # ------------------------------------------------------------------

    def _handle_ipv4(self, event: FrameArrival, pkt: IPv4Packet) -> None:
        """Process an IPv4 packet — forward or drop."""

        # Check if the packet is destined for us (one of our interface IPs)
        for iface in self._device.interfaces.values():
            if iface.ip_config and iface.ip_config.address == pkt.dst:
                # Packet is for us — handle ICMP echo
                if pkt.protocol == IPv4Packet.PROTOCOL_ICMP:
                    assert isinstance(pkt.payload, ICMPMessage)
                    if pkt.payload.type == ICMPMessage.ECHO_REQUEST:
                        self._send_icmp_echo_reply(event, pkt)
                return

        # Decrement TTL
        new_ttl = pkt.ttl - 1
        if new_ttl <= 0:
            # TTL exceeded — drop
            self._sim._record(FrameDropped(
                time=event.time, seq=self._sim.next_seq(),
                device_id=self.device_id,
                interface_name=event.interface_name,
                frame=event.frame,
                reason=DROP_TTL_EXCEEDED,
            ))
            return

        # Look up route
        route = self._routing_table.lookup(pkt.dst)
        if route is None:
            # No route — drop
            self._sim._record(FrameDropped(
                time=event.time, seq=self._sim.next_seq(),
                device_id=self.device_id,
                interface_name=event.interface_name,
                frame=event.frame,
                reason=DROP_NO_ROUTE,
            ))
            return

        # Determine next-hop
        if route.next_hop is not None:
            next_hop_ip = route.next_hop
        else:
            # Directly connected — the destination IS the next hop
            next_hop_ip = pkt.dst

        # Check egress interface state
        egress_iface = self._device.interfaces.get(route.outgoing_interface)
        if egress_iface is None or egress_iface.admin_state == InterfaceState.DOWN:
            self._sim._record(FrameDropped(
                time=event.time, seq=self._sim.next_seq(),
                device_id=self.device_id,
                interface_name=route.outgoing_interface,
                frame=event.frame,
                reason="egress interface down",
            ))
            return

        # Create forwarded packet with decremented TTL
        forwarded_pkt = IPv4Packet(
            src=pkt.src,
            dst=pkt.dst,
            protocol=pkt.protocol,
            ttl=new_ttl,
            payload=pkt.payload,
        )

        # Check ARP cache for next-hop MAC
        if next_hop_ip in self._arp_cache:
            # Cache hit — forward immediately
            dst_mac = self._arp_cache[next_hop_ip]
            self._forward_packet(forwarded_pkt, dst_mac, route.outgoing_interface)
        else:
            # Cache miss — ARP request needed
            self._pending_arp.setdefault(next_hop_ip, []).append(
                (forwarded_pkt, route.outgoing_interface)
            )
            self._send_arp_request(next_hop_ip, route.outgoing_interface)

    def _forward_packet(self, pkt: IPv4Packet, dst_mac: MACAddress, iface_name: str) -> None:
        """Encapsulate and transmit an IPv4 packet."""
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            return

        frame = EthernetFrame(
            src_mac=iface.mac,
            dst_mac=dst_mac,
            ethertype=EthernetFrame.ETHERTYPE_IPV4,
            payload=pkt,
            frame_id=str(uuid.uuid4()),
        )

        t = self._sim.clock + 1
        seq_tx = self._sim.next_seq()
        self._sim.schedule(FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=iface_name,
            frame=frame,
        ))

    def _send_icmp_echo_reply(self, event: FrameArrival, pkt: IPv4Packet) -> None:
        """Send an ICMP echo reply back to the source."""
        assert isinstance(pkt.payload, ICMPMessage)
        iface = self._device.interfaces.get(event.interface_name)
        if iface is None:
            return

        reply_icmp = ICMPMessage(
            type=ICMPMessage.ECHO_REPLY,
            code=0,
            sequence=pkt.payload.sequence,
            identifier=pkt.payload.identifier,
        )
        reply_pkt = IPv4Packet(
            src=pkt.dst,
            dst=pkt.src,
            protocol=IPv4Packet.PROTOCOL_ICMP,
            ttl=64,
            payload=reply_icmp,
        )
        frame = EthernetFrame(
            src_mac=iface.mac,
            dst_mac=event.frame.src_mac,
            ethertype=EthernetFrame.ETHERTYPE_IPV4,
            payload=reply_pkt,
            frame_id=str(uuid.uuid4()),
        )

        t = event.time + 1
        seq_tx = self._sim.next_seq()
        self._sim.schedule(FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=event.interface_name,
            frame=frame,
        ))
