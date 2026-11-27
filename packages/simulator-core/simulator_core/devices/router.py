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
- Router-originated ping (CLI ``ping`` on a router).
- 802.1Q subinterfaces (router-on-a-stick): ``Gi0/0.10`` with
  ``encapsulation dot1Q 10`` sends and receives VLAN-10-tagged frames on
  its physical parent; a ``native`` subinterface uses untagged frames.
- CLI: ip route, show ip route.

No host I/O, no sockets, no subprocess.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
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
from simulator_core.cdp import CDPManager

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation
    from simulator_core.devices.host import PingResult


# ICMP identifier for router-originated echoes (distinct from hosts' 0xACAD).
_ROUTER_ICMP_IDENTIFIER: int = 0x1051

# Ticks between successive router-originated echo requests (matches Host).
_RTT_SPACING: int = 6

# Reason recorded for the echo IOS discards while it resolves the next hop.
DROP_ARP_PENDING = "ARP resolution pending (first echo dropped, as on IOS)"

# Reason recorded when a router-originated ping has no matching route.
DROP_ROUTER_NO_ROUTE = "no route to destination in the routing table"


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

        # Router-originated pings awaiting ARP for their next hop:
        # next_hop_ip → list of (sequence, result, dst_ip, src_ip, egress_iface)
        self._pending_ping_arp: dict[
            IPv4Address,
            list[tuple[int, "PingResult", IPv4Address, IPv4Address, str]],
        ] = {}
        # Echo requests in flight: (sequence, identifier) → (send_tick, result)
        self._pending_echo: dict[tuple[int, int], tuple[int, "PingResult"]] = {}

        # CDP manager
        hostname = device.hostname if hasattr(device, "hostname") else device.id
        self.cdp_manager = CDPManager(
            device_id=device.id,
            hostname=hostname,
            capabilities="Router",
            platform="Cisco ISR 2911",
        )

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
        and are in the UP state, then re-resolve static routes against them.

        Must be called whenever an interface's address or admin state
        changes (the CLI does this after ``ip address``, ``no ip address``,
        ``shutdown`` and ``no shutdown``), otherwise the routing table goes
        stale.
        """
        # Remove all existing connected routes
        self._routing_table._routes = [
            r for r in self._routing_table._routes
            if r.source != RouteSource.CONNECTED
        ]

        # IOS installs a connected route only while the interface is
        # up/up (administratively up AND line protocol up).
        for name, iface in self._device.interfaces.items():
            if (iface.ip_config
                    and iface.admin_state == InterfaceState.UP
                    and iface.oper_state == InterfaceState.UP):
                net = iface.ip_config.network
                self._routing_table.add_connected_route(net, name)

        self._routing_table.resolve_static_routes()

        # Cached next-hop mappings for subnets that are no longer connected
        # would let traffic leave through a dead interface; drop them.
        self._arp_cache = {
            ip: mac for ip, mac in self._arp_cache.items()
            if any(
                r.source == RouteSource.CONNECTED and ip in r.network
                for r in self._routing_table.routes
            )
        }

    # ------------------------------------------------------------------
    # FrameArrival handler
    # ------------------------------------------------------------------

    def handle_frame_arrival(self, event: FrameArrival) -> None:
        """Process a frame arriving at the router."""
        frame = event.frame

        # CDP frames are consumed locally — never forwarded.
        if frame.cdp_payload is not None:
            self.cdp_manager.update_neighbor(
                local_interface=event.interface_name,
                entry=frame.cdp_payload,
                current_tick=event.time,
            )
            return

        # 802.1Q demultiplexing: hand the frame to the subinterface that owns
        # its VLAN (or to the physical port when untagged and no native
        # subinterface exists).  Frames for VLANs with no subinterface are
        # not ours.
        logical = self._ingress_interface(event.interface_name, frame.vlan_tag)
        if logical is None:
            return
        if logical != event.interface_name:
            event = replace(event, interface_name=logical)

        if frame.ethertype == EthernetFrame.ETHERTYPE_ARP:
            # Router participates in ARP for its own interfaces
            from simulator_core.frames import ARPMessage
            assert isinstance(frame.payload, ARPMessage)
            self._handle_arp(event, frame.payload)

        elif frame.ethertype == EthernetFrame.ETHERTYPE_IPV4:
            assert isinstance(frame.payload, IPv4Packet)
            # A router only routes frames addressed to its own interface MAC.
            # Unicast frames a switch flooded towards it (unknown destination)
            # belong to another station and must not be routed a second time.
            iface = self._device.interfaces.get(event.interface_name)
            if (iface is not None and not frame.dst_mac.is_broadcast
                    and frame.dst_mac != iface.mac):
                return
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
            self._unblock_pending_pings(arp.sender_ip, arp.sender_mac)

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
        self._schedule_tx(FrameTransmit(
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
        self._schedule_tx(FrameTransmit(
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
                    elif pkt.payload.type == ICMPMessage.ECHO_REPLY:
                        self._complete_echo(event.time, pkt.payload)
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
        self._schedule_tx(FrameTransmit(
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
        self._schedule_tx(FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=event.interface_name,
            frame=frame,
        ))

    # ------------------------------------------------------------------
    # Router-originated ping
    # ------------------------------------------------------------------

    def ping(self, dst_ip: str, count: int = 5) -> "PingResult":
        """
        Send *count* ICMP echo requests from this router to *dst_ip*.

        The source address is the egress interface's address, chosen by a
        routing-table lookup, as on IOS.  When the next hop is not yet in the
        ARP cache the first echo is discarded while ARP resolves, producing
        the familiar ``.!!!!`` of a router's first ping.

        Returns a PingResult that fills in as the simulation runs; call
        ``simulation.run()`` afterwards.
        """
        from simulator_core.devices.host import EchoResult, PingResult

        dst = IPv4Address(dst_ip)
        result = PingResult(target_ip=dst_ip, count=count, sent=count, received=0)

        # Each ping is a self-contained run: echoes from an earlier ping that
        # never resolved or never got a reply have timed out and must not be
        # sent (or matched) now.
        self._pending_ping_arp.clear()
        self._pending_echo.clear()

        def fail_all(reason: str) -> "PingResult":
            for seq in range(count):
                result.results.append(EchoResult(
                    sequence=seq, success=False, rtt_ticks=None, drop_reason=reason,
                ))
            return result

        # Pinging one of our own up interfaces is answered locally.
        for iface in self._device.interfaces.values():
            if (iface.ip_config and iface.ip_config.address == dst
                    and iface.admin_state == InterfaceState.UP):
                for seq in range(count):
                    result.results.append(EchoResult(
                        sequence=seq, success=True, rtt_ticks=0, drop_reason=None,
                    ))
                result.received = count
                return result

        route = self._routing_table.lookup(dst)
        if route is None:
            return fail_all(DROP_ROUTER_NO_ROUTE)
        egress = self._device.interfaces.get(route.outgoing_interface)
        if (egress is None or egress.ip_config is None
                or egress.admin_state == InterfaceState.DOWN):
            return fail_all("egress interface down")

        next_hop = route.next_hop if route.next_hop is not None else dst
        src_ip = egress.ip_config.address

        if next_hop in self._arp_cache:
            mac = self._arp_cache[next_hop]
            for seq in range(count):
                self._schedule_router_echo(
                    dst, src_ip, mac, egress.name, seq, result,
                    self._sim.clock + 1 + seq * _RTT_SPACING,
                )
            return result

        # ARP miss: IOS drops the echo that triggered resolution.
        result.results.append(EchoResult(
            sequence=0, success=False, rtt_ticks=None, drop_reason=DROP_ARP_PENDING,
        ))
        pending = self._pending_ping_arp.setdefault(next_hop, [])
        for seq in range(1, count):
            pending.append((seq, result, dst, src_ip, egress.name))
        self._send_arp_request(next_hop, egress.name)
        return result

    def _unblock_pending_pings(self, ip: IPv4Address, mac: MACAddress) -> None:
        """ARP reply for a ping's next hop — send the waiting echoes."""
        pending = self._pending_ping_arp.pop(ip, [])
        for k, (seq, result, dst, src_ip, iface_name) in enumerate(pending):
            self._schedule_router_echo(
                dst, src_ip, mac, iface_name, seq, result,
                self._sim.clock + 1 + k * _RTT_SPACING,
            )

    def _schedule_router_echo(
        self,
        dst: IPv4Address,
        src_ip: IPv4Address,
        dst_mac: MACAddress,
        iface_name: str,
        sequence: int,
        result: "PingResult",
        t: int,
    ) -> None:
        iface = self._device.interfaces.get(iface_name)
        if iface is None:
            return
        icmp = ICMPMessage(
            type=ICMPMessage.ECHO_REQUEST,
            code=0,
            sequence=sequence,
            identifier=_ROUTER_ICMP_IDENTIFIER,
        )
        pkt = IPv4Packet(
            src=src_ip, dst=dst,
            protocol=IPv4Packet.PROTOCOL_ICMP,
            ttl=255,
            payload=icmp,
        )
        frame = EthernetFrame(
            src_mac=iface.mac,
            dst_mac=dst_mac,
            ethertype=EthernetFrame.ETHERTYPE_IPV4,
            payload=pkt,
            frame_id=str(uuid.uuid4()),
        )
        self._schedule_tx(FrameTransmit(
            time=t, seq=self._sim.next_seq(),
            device_id=self.device_id,
            interface_name=iface_name,
            frame=frame,
        ))
        self._pending_echo[(sequence, _ROUTER_ICMP_IDENTIFIER)] = (t, result)

    def _complete_echo(self, arrive_time: int, icmp: ICMPMessage) -> None:
        """Record an echo reply for a router-originated ping."""
        from simulator_core.devices.host import EchoResult

        entry = self._pending_echo.pop((icmp.sequence, icmp.identifier), None)
        if entry is None:
            return  # not ours — ignore
        send_tick, result = entry
        result.received += 1
        result.results.append(EchoResult(
            sequence=icmp.sequence,
            success=True,
            rtt_ticks=arrive_time - send_tick,
            drop_reason=None,
        ))

    # ------------------------------------------------------------------
    # 802.1Q subinterfaces
    # ------------------------------------------------------------------

    def _ingress_interface(self, physical: str, vlan_tag: Optional[int]) -> Optional[str]:
        """Logical interface that receives a frame arriving on *physical*."""
        subifs = [
            i for i in self._device.interfaces.values()
            if i.is_subinterface and i.parent_name == physical and i.dot1q_vlan is not None
        ]
        if vlan_tag is not None:
            match = next((i for i in subifs if i.dot1q_vlan == vlan_tag and not i.dot1q_native), None)
            return match.name if match else None
        native = next((i for i in subifs if i.dot1q_native), None)
        return native.name if native else physical

    def _schedule_tx(self, event: FrameTransmit) -> None:
        """
        Schedule a transmit, translating a subinterface into its physical
        parent plus the subinterface's 802.1Q tag (none for the native VLAN).
        """
        iface = self._device.interfaces.get(event.interface_name)
        if iface is not None and iface.is_subinterface:
            if iface.dot1q_vlan is None:
                return  # no encapsulation configured: cannot send
            tag = None if iface.dot1q_native else iface.dot1q_vlan
            event = replace(
                event,
                interface_name=iface.parent_name,
                frame=replace(event.frame, vlan_tag=tag),
            )
        self._sim.schedule(event)
