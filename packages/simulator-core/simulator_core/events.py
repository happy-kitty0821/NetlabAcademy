"""
simulator_core.events
~~~~~~~~~~~~~~~~~~~~~
The complete SimulationEvent hierarchy for the proof-of-concept simulator.

All event types are immutable frozen dataclasses that inherit from
SimulationEvent.  The class itself is the discriminator — no string-typed
``"type"`` field is needed for dispatch.

Drop reason constants are module-level strings so callers can import and
compare against them without hard-coding strings.

No host I/O, no socket imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from simulator_core.frames import ARPMessage, EthernetFrame, ICMPMessage


# ---------------------------------------------------------------------------
# Drop reason constants
# ---------------------------------------------------------------------------
# These are the only valid values for FrameDropped.reason in this PoC.
# Stage B/C will extend the list.

DROP_INTERFACE_ADMIN_DOWN: str = "interface administratively down"
DROP_PORT_DOWN: str = "port down"
DROP_NO_ROUTE: str = "no route to host — destination outside local subnet and no gateway configured"
DROP_TTL_EXCEEDED: str = "TTL exceeded"
DROP_UNRESOLVABLE_ARP: str = "ARP unresolvable — target unreachable"
DROP_LINK_DOWN: str = "link down"


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulationEvent:
    """
    Base class for all simulation events.

    Attributes
    ----------
    time:
        Logical tick at which this event occurs.
    seq:
        Tie-breaker: a monotonically increasing integer assigned by the
        EventScheduler at schedule time.  Guarantees total ordering for
        events with the same logical timestamp.
    """

    time: int   # logical tick
    seq: int    # assigned by EventScheduler.next_seq()


# ---------------------------------------------------------------------------
# Frame delivery events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameTransmit(SimulationEvent):
    """
    A device has placed a frame on one of its interfaces for transmission.
    The simulation engine converts this into a FrameArrival on the peer
    interface after PROPAGATION_DELAY ticks.
    """

    device_id: str
    interface_name: str
    frame: EthernetFrame


@dataclass(frozen=True)
class FrameArrival(SimulationEvent):
    """
    A frame has arrived at a device interface.
    The owning device protocol handler processes this event.
    """

    device_id: str
    interface_name: str
    frame: EthernetFrame


@dataclass(frozen=True)
class FrameDropped(SimulationEvent):
    """
    A frame was dropped at a device.

    Attributes
    ----------
    device_id:
        The device that dropped the frame.
    interface_name:
        The interface where the drop occurred, or ``None`` if the drop
        happened before an interface was identified (e.g. no route).
    frame:
        The frame that was dropped.
    reason:
        One of the DROP_* constants defined in this module.
    """

    device_id: str
    interface_name: Optional[str]
    frame: EthernetFrame
    reason: str


# ---------------------------------------------------------------------------
# ARP events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ARPRequestSent(SimulationEvent):
    """A host has originated an ARP request."""

    device_id: str
    message: ARPMessage


@dataclass(frozen=True)
class ARPReplySent(SimulationEvent):
    """A host has originated an ARP reply."""

    device_id: str
    message: ARPMessage


@dataclass(frozen=True)
class ARPCacheUpdated(SimulationEvent):
    """A host's ARP cache gained a new or updated entry."""

    device_id: str
    ip_address: str     # IPv4Address.__str__()
    mac_address: str    # MACAddress.value


# ---------------------------------------------------------------------------
# MAC address table events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MACTableLearned(SimulationEvent):
    """The switch has learned a new source MAC address on a port."""

    switch_id: str
    mac_address: str
    interface_name: str
    vlan: int


# ---------------------------------------------------------------------------
# ICMP events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ICMPEchoRequestSent(SimulationEvent):
    """A host has originated an ICMP echo request."""

    src_device_id: str
    dst_device_id: str
    message: ICMPMessage


@dataclass(frozen=True)
class ICMPEchoReplySent(SimulationEvent):
    """A host has originated an ICMP echo reply."""

    src_device_id: str
    dst_device_id: str
    message: ICMPMessage


# ---------------------------------------------------------------------------
# Limit / sentinel events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceLimitReached(SimulationEvent):
    """
    Sentinel appended to the trace when the trace size cap is hit.
    The simulation may continue running; trace recording stops.
    """

    limit: int


# ---------------------------------------------------------------------------
# Convenience registry (used by serialisation)
# ---------------------------------------------------------------------------

#: Maps class name → event class for deserialisation.
EVENT_REGISTRY: dict[str, type[SimulationEvent]] = {
    cls.__name__: cls  # type: ignore[type-abstract]
    for cls in [
        FrameTransmit,
        FrameArrival,
        FrameDropped,
        ARPRequestSent,
        ARPReplySent,
        ARPCacheUpdated,
        MACTableLearned,
        ICMPEchoRequestSent,
        ICMPEchoReplySent,
        TraceLimitReached,
    ]
}
