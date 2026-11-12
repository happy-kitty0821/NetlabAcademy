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

    @property
    def device_id(self) -> str:
        """Convenience alias so the canvas can treat this like other events."""
        return self.src_device_id


@dataclass(frozen=True)
class ICMPEchoReplySent(SimulationEvent):
    """A host has originated an ICMP echo reply."""

    src_device_id: str
    dst_device_id: str
    message: ICMPMessage

    @property
    def device_id(self) -> str:
        """Convenience alias so the canvas can treat this like other events."""
        return self.src_device_id


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
# Routing events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteAdded(SimulationEvent):
    """A route was added to a router's routing table."""
    device_id: str
    network: str    # e.g. "10.0.0.0/8"
    next_hop: str   # e.g. "192.168.1.254" or "connected"
    source: str     # "connected" or "static"


@dataclass(frozen=True)
class RouteRemoved(SimulationEvent):
    """A route was removed from a router's routing table."""
    device_id: str
    network: str


# ---------------------------------------------------------------------------
# STP hello timer event (Phase 3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BPDUHelloEvent(SimulationEvent):
    """
    Periodic BPDU transmission trigger for a single switch.

    Processed by the simulation dispatcher to call send_bpdus() for the
    named switch and immediately reschedule the next BPDUHelloEvent.

    Fields
    ------
    device_id:
        The switch that should transmit BPDUs on this tick.
    generation:
        Monotonically increasing counter per switch.  When a reset() or
        topology change increments the switch's generation, any queued
        BPDUHelloEvent with an older generation is silently dropped,
        ensuring at most one active hello chain per switch.
    """
    device_id: str
    generation: int


@dataclass(frozen=True)
class ForwardDelayEvent(SimulationEvent):
    """
    Transition a port from LEARNING → FORWARDING after forward_delay ticks.

    Fields
    ------
    device_id:
        The switch owning the port.
    interface_name:
        The port being transitioned.
    vlan_id:
        The VLAN STP instance the port belongs to.
    generation:
        The simulation hello generation at event-creation time.  If the
        switch's generation has changed by the time this event fires, the
        port's state may have already been updated — the handler re-checks
        that the port is still in LEARNING before transitioning.
    """
    device_id: str
    interface_name: str
    vlan_id: int
    generation: int


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
        BPDUHelloEvent,
        ForwardDelayEvent,
    ]
}
