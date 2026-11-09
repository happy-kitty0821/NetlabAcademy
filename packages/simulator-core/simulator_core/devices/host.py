"""
simulator_core.devices.host
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Host (PC / end-station) device protocol logic.

Responsibilities:
- IPv4 addressing and pre-flight route checking.
- ARP cache management and ARP request/reply generation.
- ICMP echo request/reply handling (ping).
- FrameArrival dispatch for ARP and ICMP payloads.

The Host communicates with the rest of the simulation exclusively through
the Simulation.schedule() method — it does not directly mutate other devices.

No host I/O, no socket imports.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Optional

from simulator_core.addresses import BROADCAST_MAC, MACAddress, ZERO_MAC
from simulator_core.events import (
    ARPCacheUpdated,
    ARPReplySent,
    ARPRequestSent,
    FrameArrival,
    FrameDropped,
    FrameTransmit,
    ICMPEchoReplySent,
    ICMPEchoRequestSent,
    DROP_INTERFACE_ADMIN_DOWN,
    DROP_NO_ROUTE,
)
from simulator_core.exceptions import ConfigurationError
from simulator_core.frames import (
    ARPMessage,
    EthernetFrame,
    ICMPMessage,
    IPv4Packet,
)
from simulator_core.topology import Device
from simulator_core.types import DEFAULT_VLAN, InterfaceState

if TYPE_CHECKING:
    from simulator_core.simulation import Simulation


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EchoResult:
    """Result for a single ICMP echo exchange."""

    sequence: int
    success: bool
    rtt_ticks: Optional[int]   # None if no reply received
    drop_reason: Optional[str]  # set when success is False


@dataclass
class PingResult:
    """Aggregate result for a ping session (one or more echo requests)."""

    target_ip: str
    count: int
    sent: int
    received: int
    results: list[EchoResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Host protocol object
# ---------------------------------------------------------------------------

# Identifier used for all ICMP echo messages from a given Host instance.
# Using a fixed constant keeps the simulation deterministic.
_ICMP_IDENTIFIER: int = 0xACAD  # "ACAD" — NetLab Academy marker


class Host:
    """
    Protocol logic for a simulated end-host (PC / server).

    One Host instance exists per HOST-model Device in the Simulation.
    """

    def __init__(self, device: Device, simulation: "Simulation") -> None:
        self._device = device
        self._sim = simulation

        # ARP cache: IPv4Address → MACAddress
        self._arp_cache: dict[IPv4Address, MACAddress] = {}

        # Pending pings awaiting ARP resolution:
        # dst_ip → list of (sequence, ping_result)
        self._pending_arp: dict[IPv4Address, list[tuple[int, PingResult]]] = {}

        # Pending echo requests awaiting reply:
        # (sequence, identifier) → (send_tick, ping_result)
        self._pending_echo: dict[tuple[int, int], tuple[int, PingResult]] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_id(self) -> str:
        return self._device.id

    @property
    def arp_cache(self) -> dict[IPv4Address, MACAddress]:
        """Read-only view of the ARP cache."""
        return dict(self._arp_cache)

    # ------------------------------------------------------------------
    # Configuration helpers (delegating to topology Interface)
    # ------------------------------------------------------------------

    def _primary_interface(self):  # -> Interface
        """Return the first (and only, for PoC) interface on this host."""
        ifaces = list(self._device.interfaces.values())
        if not ifaces:
            raise ConfigurationError(
                f"Host {self._device.hostname!r} has no interfaces."
            )
        return ifaces[0]

    def _own_ip(self) -> Optional[IPv4Address]:
        iface = self._primary_interface()
        if iface.ip_config is None:
            return None
        return iface.ip_config.address

    def _own_mac(self) -> MACAddress:
        return self._primary_interface().mac

    def _own_iface_name(self) -> str:
        return self._primary_interface().name

    # ------------------------------------------------------------------
    # Ping — public API
    # ------------------------------------------------------------------

    def ping(self, dst_ip: str, count: int = 4) -> PingResult:
        """
        Initiate a ping from this host to *dst_ip*.

        Pre-flight checks:
        1. Raises ConfigurationError if the source interface has no IP.
        2. Returns a failed PingResult (no events scheduled) if *dst_ip* is
           outside the local subnet and no default gateway is configured.

        Otherwise, schedules ARP (if needed) and ICMP echo events.

        Returns the PingResult object, which is populated asynchronously as
        the simulation runs.  Call simulation.run() after ping() to fill it.
        """
        # --- Validate source IP ---
        own_ip = self._own_ip()
        if own_ip is None:
            raise ConfigurationError(
                f"Host {self._device.hostname!r} cannot ping: no IP address "
                f"configured on interface {self._own_iface_name()!r}."
            )

        dst = IPv4Address(dst_ip)
        iface = self._primary_interface()
        own_iface_config = iface.ip_config  # IPv4Interface

        # --- Pre-flight: interface admin state ---
        # If the interface is down, we still schedule the events so the trace
        # captures a FrameDropped.  The drop is generated by the frame delivery
        # path in Simulation._deliver_frame().

        # --- Pre-flight: route check ---
        # Check if dst is in the same subnet.  If not, we need a gateway.
        in_local_subnet = dst in own_iface_config.network

        if not in_local_subnet:
            gateway = iface.default_gateway
            if gateway is None:
                # Deterministic pre-flight failure — no events scheduled.
                result = PingResult(
                    target_ip=dst_ip,
                    count=count,
                    sent=count,
                    received=0,
                )
                for seq in range(count):
                    result.results.append(EchoResult(
                        sequence=seq,
                        success=False,
                        rtt_ticks=None,
                        drop_reason=DROP_NO_ROUTE,
                    ))
                return result

        # --- Build the PingResult (to be filled as simulation runs) ---
        result = PingResult(target_ip=dst_ip, count=count, sent=count, received=0)

        # --- Schedule ARP + ICMP ---
        if dst in self._arp_cache:
            # Cache hit: schedule ICMP immediately.
            dst_mac = self._arp_cache[dst]
            for seq in range(count):
                self._schedule_echo_request(dst, dst_mac, seq, result)
        else:
            # Cache miss: schedule ARP broadcast, register pending ping.
            self._schedule_arp_request(dst, own_ip)
            pending = self._pending_arp.setdefault(dst, [])
            for seq in range(count):
                pending.append((seq, result))

        return result

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_frame_arrival(self, event: FrameArrival) -> None:
        """Dispatch an incoming frame to the correct protocol handler."""
        frame = event.frame
        if frame.ethertype == EthernetFrame.ETHERTYPE_ARP:
            assert isinstance(frame.payload, ARPMessage)
            self._handle_arp(event, frame.payload)
        elif frame.ethertype == EthernetFrame.ETHERTYPE_IPV4:
            assert isinstance(frame.payload, IPv4Packet)
            self._handle_ipv4(event, frame.payload)

    def _handle_arp(self, event: FrameArrival, arp: ARPMessage) -> None:
        """Process an arriving ARP message."""
        own_ip = self._own_ip()
        if own_ip is None:
            return  # no IP — ignore

        # Always learn the sender's mapping.
        self._learn_arp(event.time, arp.sender_ip, arp.sender_mac)

        if arp.operation == ARPMessage.ARP_REQUEST and arp.target_ip == own_ip:
            # We are the target — send a reply.
            self._schedule_arp_reply(event, arp)

        elif arp.operation == ARPMessage.ARP_REPLY and arp.target_ip == own_ip:
            # ARP reply addressed to us — unblock pending pings.
            self._unblock_pending_pings(event.time, arp.sender_ip, arp.sender_mac)

    def _handle_ipv4(self, event: FrameArrival, pkt: IPv4Packet) -> None:
        """Process an arriving IPv4 packet."""
        own_ip = self._own_ip()
        if own_ip is None or pkt.dst != own_ip:
            return  # not addressed to us

        if pkt.protocol == IPv4Packet.PROTOCOL_ICMP:
            assert isinstance(pkt.payload, ICMPMessage)
            icmp = pkt.payload
            if icmp.type == ICMPMessage.ECHO_REQUEST:
                self._schedule_icmp_reply(event, pkt, icmp)
            elif icmp.type == ICMPMessage.ECHO_REPLY:
                self._complete_echo(event.time, icmp)

    # ------------------------------------------------------------------
    # ARP scheduling helpers
    # ------------------------------------------------------------------

    def _schedule_arp_request(self, target_ip: IPv4Address, own_ip: IPv4Address) -> None:
        """Broadcast an ARP request for *target_ip*."""
        own_mac = self._own_mac()
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
        arp_event = ARPRequestSent(
            time=t, seq=seq_req,
            device_id=self.device_id,
            message=arp_msg,
        )
        self._sim.schedule(arp_event)

        seq_tx = self._sim.next_seq()
        tx_event = FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=self._own_iface_name(),
            frame=frame,
        )
        self._sim.schedule(tx_event)

    def _schedule_arp_reply(self, event: FrameArrival, request: ARPMessage) -> None:
        """Send a unicast ARP reply to the requester."""
        own_mac = self._own_mac()
        own_ip = self._own_ip()
        assert own_ip is not None
        t = event.time + 1

        arp_reply = ARPMessage(
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
            payload=arp_reply,
            frame_id=str(uuid.uuid4()),
        )

        seq_reply = self._sim.next_seq()
        reply_event = ARPReplySent(
            time=t, seq=seq_reply,
            device_id=self.device_id,
            message=arp_reply,
        )
        self._sim.schedule(reply_event)

        seq_tx = self._sim.next_seq()
        tx_event = FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=self._own_iface_name(),
            frame=frame,
        )
        self._sim.schedule(tx_event)

    # ------------------------------------------------------------------
    # ARP cache helpers
    # ------------------------------------------------------------------

    def _learn_arp(self, time: int, ip: IPv4Address, mac: MACAddress) -> None:
        """Update ARP cache and record an ARPCacheUpdated event."""
        self._arp_cache[ip] = mac
        seq = self._sim.next_seq()
        evt = ARPCacheUpdated(
            time=time, seq=seq,
            device_id=self.device_id,
            ip_address=str(ip),
            mac_address=mac.value,
        )
        self._sim.schedule(evt)

    def _unblock_pending_pings(
        self,
        time: int,
        sender_ip: IPv4Address,
        sender_mac: MACAddress,
    ) -> None:
        """ARP reply received — schedule waiting ICMP echo requests."""
        pending = self._pending_arp.pop(sender_ip, [])
        for seq, result in pending:
            self._schedule_echo_request(sender_ip, sender_mac, seq, result)

    # ------------------------------------------------------------------
    # ICMP scheduling helpers
    # ------------------------------------------------------------------

    def _schedule_echo_request(
        self,
        dst_ip: IPv4Address,
        dst_mac: MACAddress,
        sequence: int,
        result: PingResult,
    ) -> None:
        """
        Schedule one ICMP echo request and register it as pending.

        Each request is offset by its sequence number so requests are
        spaced one tick apart and the trace interleaves correctly:
          seq 0 → clock + 2
          seq 1 → clock + 3
          seq 2 → clock + 4
          ...
        This mirrors a real host where each echo request is sent after
        the previous one, not all simultaneously.
        """
        own_ip = self._own_ip()
        own_mac = self._own_mac()
        assert own_ip is not None

        # Space each request enough that the previous one has completed
        # its full round trip before the next is sent.
        # Round-trip path: host→switch (1 tick) + switch→host-b (1 tick)
        # + processing (1 tick) + reply path (2 ticks) = ~5 ticks per ping.
        # Using 6 ticks between requests gives headroom and clean separation.
        RTT_SPACING = 6
        t = self._sim.clock + 2 + sequence * RTT_SPACING

        icmp = ICMPMessage(
            type=ICMPMessage.ECHO_REQUEST,
            code=0,
            sequence=sequence,
            identifier=_ICMP_IDENTIFIER,
        )
        pkt = IPv4Packet(
            src=own_ip, dst=dst_ip,
            protocol=IPv4Packet.PROTOCOL_ICMP,
            ttl=64,
            payload=icmp,
        )
        frame = EthernetFrame(
            src_mac=own_mac,
            dst_mac=dst_mac,
            ethertype=EthernetFrame.ETHERTYPE_IPV4,
            payload=pkt,
            frame_id=str(uuid.uuid4()),
        )

        seq_icmp = self._sim.next_seq()
        icmp_event = ICMPEchoRequestSent(
            time=t, seq=seq_icmp,
            src_device_id=self.device_id,
            dst_device_id="unknown",
            message=icmp,
        )
        self._sim.schedule(icmp_event)

        seq_tx = self._sim.next_seq()
        tx_event = FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=self._own_iface_name(),
            frame=frame,
        )
        self._sim.schedule(tx_event)

        # Register as pending — keyed by (sequence, identifier).
        self._pending_echo[(sequence, _ICMP_IDENTIFIER)] = (t, result)

    def _schedule_icmp_reply(
        self,
        event: FrameArrival,
        pkt: IPv4Packet,
        icmp: ICMPMessage,
    ) -> None:
        """
        Schedule an ICMP echo reply in response to a received request.

        The reply is sent at event.time + 1, which is naturally spaced
        because the requests themselves arrive at different ticks (seq 0
        arrives at tick T, seq 1 at T+1, etc.) thanks to the spacing fix
        in _schedule_echo_request.
        """
        own_ip = self._own_ip()
        own_mac = self._own_mac()
        assert own_ip is not None

        t = event.time + 1

        reply_icmp = ICMPMessage(
            type=ICMPMessage.ECHO_REPLY,
            code=0,
            sequence=icmp.sequence,
            identifier=icmp.identifier,
        )
        reply_pkt = IPv4Packet(
            src=own_ip, dst=pkt.src,
            protocol=IPv4Packet.PROTOCOL_ICMP,
            ttl=64,
            payload=reply_icmp,
        )
        dst_mac = event.frame.src_mac
        reply_frame = EthernetFrame(
            src_mac=own_mac,
            dst_mac=dst_mac,
            ethertype=EthernetFrame.ETHERTYPE_IPV4,
            payload=reply_pkt,
            frame_id=str(uuid.uuid4()),
        )

        seq_icmp = self._sim.next_seq()
        icmp_event = ICMPEchoReplySent(
            time=t, seq=seq_icmp,
            src_device_id=self.device_id,
            dst_device_id="unknown",
            message=reply_icmp,
        )
        self._sim.schedule(icmp_event)

        seq_tx = self._sim.next_seq()
        tx_event = FrameTransmit(
            time=t, seq=seq_tx,
            device_id=self.device_id,
            interface_name=self._own_iface_name(),
            frame=reply_frame,
        )
        self._sim.schedule(tx_event)

    def _complete_echo(self, arrive_time: int, icmp: ICMPMessage) -> None:
        """Record the ICMP echo reply in the pending PingResult."""
        key = (icmp.sequence, icmp.identifier)
        entry = self._pending_echo.pop(key, None)
        if entry is None:
            return  # unsolicited reply — ignore
        send_tick, result = entry
        rtt = arrive_time - send_tick
        result.received += 1
        result.results.append(EchoResult(
            sequence=icmp.sequence,
            success=True,
            rtt_ticks=rtt,
            drop_reason=None,
        ))
