"""
simulator_core.frames
~~~~~~~~~~~~~~~~~~~~~
Wire-format domain objects: Ethernet frames, ARP messages, IPv4 packets and
ICMP messages.

All types are immutable frozen dataclasses.  They represent what is on the
wire; no mutable state lives here.

No host I/O, no socket imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Optional, Union

from simulator_core.addresses import MACAddress

if TYPE_CHECKING:
    from simulator_core.stp import BPDU


# ---------------------------------------------------------------------------
# STP multicast MAC and ethertype sentinel
# ---------------------------------------------------------------------------

#: IEEE 802.1D STP multicast destination MAC address.
STP_MULTICAST_MAC: str = "01:80:c2:00:00:00"


# ---------------------------------------------------------------------------
# ARP (RFC 826)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ARPMessage:
    """
    An ARP request or reply payload.

    Attributes
    ----------
    operation:
        1 = ARP request, 2 = ARP reply.
    sender_mac:
        MAC address of the sender.
    sender_ip:
        IPv4 address of the sender.
    target_mac:
        MAC address of the target.  For requests this is the zero MAC
        (``00:00:00:00:00:00``) because the sender does not yet know it.
    target_ip:
        IPv4 address being queried (request) or confirmed (reply).
    """

    operation: int          # 1 = request, 2 = reply
    sender_mac: MACAddress
    sender_ip: IPv4Address
    target_mac: MACAddress  # zero MAC for requests
    target_ip: IPv4Address

    ARP_REQUEST: int = 1
    ARP_REPLY: int = 2


# ---------------------------------------------------------------------------
# ICMP (RFC 792 subset — echo only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ICMPMessage:
    """
    An ICMP echo request or echo reply payload (type 8 or type 0).

    Attributes
    ----------
    type:
        8 = echo request, 0 = echo reply.
    code:
        Always 0 for echo request/reply.
    sequence:
        Echo sequence number (monotonically increasing per ping session).
    identifier:
        Echo identifier — used to associate replies with the originating host.
    payload:
        Optional data bytes (not inspected by the simulator in this PoC).
    """

    type: int       # 8 = echo request, 0 = echo reply
    code: int
    sequence: int
    identifier: int
    payload: bytes = b""

    ECHO_REQUEST: int = 8
    ECHO_REPLY: int = 0


# ---------------------------------------------------------------------------
# IPv4 packet (RFC 791 minimal subset)
# ---------------------------------------------------------------------------

# Type alias for payloads carried inside an IPv4 packet.
# Extend this union when adding UDP/TCP support.
IPv4Payload = ICMPMessage


@dataclass(frozen=True)
class IPv4Packet:
    """
    An IPv4 packet header and payload.

    Only the fields relevant to the simulator's forwarding model are present.

    Attributes
    ----------
    src:
        Source IPv4 address.
    dst:
        Destination IPv4 address.
    protocol:
        IP protocol number: 1 = ICMP.
    ttl:
        Time-to-live hop count.  Decremented on each router hop (Stage C).
    payload:
        The encapsulated payload (ICMPMessage in this PoC).
    """

    src: IPv4Address
    dst: IPv4Address
    protocol: int           # 1 = ICMP
    ttl: int
    payload: IPv4Payload

    PROTOCOL_ICMP: int = 1


# ---------------------------------------------------------------------------
# Ethernet frame
# ---------------------------------------------------------------------------

# Type alias for payloads carried inside an Ethernet frame.
EthernetPayload = Union[IPv4Packet, ARPMessage]


@dataclass(frozen=True)
class EthernetFrame:
    """
    An Ethernet II frame.

    Attributes
    ----------
    src_mac:
        Source MAC address.
    dst_mac:
        Destination MAC address (unicast, multicast, or broadcast).
    ethertype:
        EtherType field: 0x0800 = IPv4, 0x0806 = ARP, 0x0027 = BPDU sentinel.
    frame_id:
        A UUID string assigned at creation time.  Not part of the wire format;
        used to correlate events in the trace.
    payload:
        The encapsulated IP/ARP payload.  ``None`` for BPDU frames which
        carry their data in ``bpdu_payload``.
    bpdu_payload:
        BPDU carried by this frame.  Set only for STP BPDU frames; ``None``
        for all other frame types.
    """

    # Required fields (no defaults) must come before optional fields.
    src_mac: MACAddress
    dst_mac: MACAddress
    ethertype: int          # 0x0800 = IPv4, 0x0806 = ARP, 0x0027 = BPDU
    frame_id: str           # UUID assigned by caller
    payload: Optional[EthernetPayload] = None
    bpdu_payload: Optional["BPDU"] = None

    ETHERTYPE_IPV4: int = 0x0800
    ETHERTYPE_ARP: int = 0x0806
    #: LLC-based STP BPDU sentinel ethertype (not a real EtherType II value;
    #: used as a unique discriminator within the simulator).
    ETHERTYPE_BPDU: int = 0x0027
