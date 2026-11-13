"""
simulator_core.serialisation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
JSON serialisation and deserialisation for the simulation event trace.

Design
------
Each event class registers ``to_dict`` and ``from_dict`` implementations via
the :data:`_SERIALISERS` and :data:`_DESERIALISERS` mappings.  The public
helpers :func:`trace_to_json` and :func:`trace_from_json` delegate to these.

No ``eval``, no ``exec``, no ``pickle`` are used.  Only ``json``-safe Python
primitives (str, int, float, bool, list, dict, None) appear in the output.

No host I/O, no socket imports.
"""

from __future__ import annotations

from ipaddress import IPv4Address
from typing import Any

from simulator_core.addresses import MACAddress, ZERO_MAC
from simulator_core.events import (
    ARPCacheUpdated,
    ARPReplySent,
    ARPRequestSent,
    BPDUHelloEvent,
    CDPHelloEvent,
    EVENT_REGISTRY,
    ForwardDelayEvent,
    FrameArrival,
    FrameDropped,
    FrameTransmit,
    ICMPEchoReplySent,
    ICMPEchoRequestSent,
    MACTableLearned,
    SimulationEvent,
    TraceLimitReached,
)
from simulator_core.frames import ARPMessage, EthernetFrame, ICMPMessage, IPv4Packet


# ---------------------------------------------------------------------------
# Helpers: primitive types → dict and back
# ---------------------------------------------------------------------------


def _mac_to_str(mac: MACAddress) -> str:
    return mac.value


def _mac_from_str(s: str) -> MACAddress:
    return MACAddress(s)


def _ip_to_str(ip: IPv4Address) -> str:
    return str(ip)


def _ip_from_str(s: str) -> IPv4Address:
    return IPv4Address(s)


def _arp_to_dict(arp: ARPMessage) -> dict[str, Any]:
    return {
        "operation": arp.operation,
        "sender_mac": _mac_to_str(arp.sender_mac),
        "sender_ip": _ip_to_str(arp.sender_ip),
        "target_mac": _mac_to_str(arp.target_mac),
        "target_ip": _ip_to_str(arp.target_ip),
    }


def _arp_from_dict(d: dict[str, Any]) -> ARPMessage:
    return ARPMessage(
        operation=d["operation"],
        sender_mac=_mac_from_str(d["sender_mac"]),
        sender_ip=_ip_from_str(d["sender_ip"]),
        target_mac=_mac_from_str(d["target_mac"]),
        target_ip=_ip_from_str(d["target_ip"]),
    )


def _icmp_to_dict(icmp: ICMPMessage) -> dict[str, Any]:
    return {
        "type": icmp.type,
        "code": icmp.code,
        "sequence": icmp.sequence,
        "identifier": icmp.identifier,
        "payload": icmp.payload.hex(),
    }


def _icmp_from_dict(d: dict[str, Any]) -> ICMPMessage:
    return ICMPMessage(
        type=d["type"],
        code=d["code"],
        sequence=d["sequence"],
        identifier=d["identifier"],
        payload=bytes.fromhex(d["payload"]),
    )


def _ipv4_packet_to_dict(pkt: IPv4Packet) -> dict[str, Any]:
    return {
        "src": _ip_to_str(pkt.src),
        "dst": _ip_to_str(pkt.dst),
        "protocol": pkt.protocol,
        "ttl": pkt.ttl,
        "payload": _icmp_to_dict(pkt.payload),  # only ICMP in PoC
    }


def _ipv4_packet_from_dict(d: dict[str, Any]) -> IPv4Packet:
    return IPv4Packet(
        src=_ip_from_str(d["src"]),
        dst=_ip_from_str(d["dst"]),
        protocol=d["protocol"],
        ttl=d["ttl"],
        payload=_icmp_from_dict(d["payload"]),
    )


def _frame_to_dict(frame: EthernetFrame) -> dict[str, Any]:
    if frame.ethertype == EthernetFrame.ETHERTYPE_ARP:
        payload_dict = _arp_to_dict(frame.payload)  # type: ignore[arg-type]
        payload_type = "arp"
    elif frame.cdp_payload is not None:
        # CDP frames carry no IP/ARP payload
        payload_dict = {}
        payload_type = "cdp"
    elif frame.bpdu_payload is not None:
        # BPDU frames carry no IP/ARP payload
        payload_dict = {}
        payload_type = "bpdu"
    else:
        payload_dict = _ipv4_packet_to_dict(frame.payload)  # type: ignore[arg-type]
        payload_type = "ipv4"
    return {
        "src_mac": _mac_to_str(frame.src_mac),
        "dst_mac": _mac_to_str(frame.dst_mac),
        "ethertype": frame.ethertype,
        "payload_type": payload_type,
        "payload": payload_dict,
        "frame_id": frame.frame_id,
    }


def _frame_from_dict(d: dict[str, Any]) -> EthernetFrame:
    if d["payload_type"] == "arp":
        payload = _arp_from_dict(d["payload"])
        return EthernetFrame(
            src_mac=_mac_from_str(d["src_mac"]),
            dst_mac=_mac_from_str(d["dst_mac"]),
            ethertype=d["ethertype"],
            payload=payload,
            frame_id=d["frame_id"],
        )
    elif d["payload_type"] in ("cdp", "bpdu"):
        # CDP and BPDU frames have no serialisable payload in this implementation;
        # reconstruct as a bare frame (payload=None) for trace round-trip purposes.
        return EthernetFrame(
            src_mac=_mac_from_str(d["src_mac"]),
            dst_mac=_mac_from_str(d["dst_mac"]),
            ethertype=d["ethertype"],
            frame_id=d["frame_id"],
        )
    else:
        payload = _ipv4_packet_from_dict(d["payload"])
        return EthernetFrame(
            src_mac=_mac_from_str(d["src_mac"]),
            dst_mac=_mac_from_str(d["dst_mac"]),
            ethertype=d["ethertype"],
            payload=payload,
            frame_id=d["frame_id"],
        )


# ---------------------------------------------------------------------------
# Per-event-class serialisers
# ---------------------------------------------------------------------------

def _base_dict(event: SimulationEvent, type_name: str) -> dict[str, Any]:
    return {"type": type_name, "time": event.time, "seq": event.seq}


def _frame_transmit_to_dict(e: FrameTransmit) -> dict[str, Any]:
    d = _base_dict(e, "FrameTransmit")
    d["device_id"] = e.device_id
    d["interface_name"] = e.interface_name
    d["frame"] = _frame_to_dict(e.frame)
    return d


def _frame_arrival_to_dict(e: FrameArrival) -> dict[str, Any]:
    d = _base_dict(e, "FrameArrival")
    d["device_id"] = e.device_id
    d["interface_name"] = e.interface_name
    d["frame"] = _frame_to_dict(e.frame)
    return d


def _frame_dropped_to_dict(e: FrameDropped) -> dict[str, Any]:
    d = _base_dict(e, "FrameDropped")
    d["device_id"] = e.device_id
    d["interface_name"] = e.interface_name
    d["frame"] = _frame_to_dict(e.frame)
    d["reason"] = e.reason
    return d


def _arp_request_sent_to_dict(e: ARPRequestSent) -> dict[str, Any]:
    d = _base_dict(e, "ARPRequestSent")
    d["device_id"] = e.device_id
    d["message"] = _arp_to_dict(e.message)
    return d


def _arp_reply_sent_to_dict(e: ARPReplySent) -> dict[str, Any]:
    d = _base_dict(e, "ARPReplySent")
    d["device_id"] = e.device_id
    d["message"] = _arp_to_dict(e.message)
    return d


def _arp_cache_updated_to_dict(e: ARPCacheUpdated) -> dict[str, Any]:
    d = _base_dict(e, "ARPCacheUpdated")
    d["device_id"] = e.device_id
    d["ip_address"] = e.ip_address
    d["mac_address"] = e.mac_address
    return d


def _mac_table_learned_to_dict(e: MACTableLearned) -> dict[str, Any]:
    d = _base_dict(e, "MACTableLearned")
    d["switch_id"] = e.switch_id
    d["mac_address"] = e.mac_address
    d["interface_name"] = e.interface_name
    d["vlan"] = e.vlan
    return d


def _icmp_echo_request_sent_to_dict(e: ICMPEchoRequestSent) -> dict[str, Any]:
    d = _base_dict(e, "ICMPEchoRequestSent")
    d["src_device_id"] = e.src_device_id
    d["dst_device_id"] = e.dst_device_id
    d["device_id"] = e.src_device_id   # canvas convenience alias
    d["message"] = _icmp_to_dict(e.message)
    return d


def _icmp_echo_reply_sent_to_dict(e: ICMPEchoReplySent) -> dict[str, Any]:
    d = _base_dict(e, "ICMPEchoReplySent")
    d["src_device_id"] = e.src_device_id
    d["dst_device_id"] = e.dst_device_id
    d["device_id"] = e.src_device_id   # canvas convenience alias
    d["message"] = _icmp_to_dict(e.message)
    return d


def _trace_limit_reached_to_dict(e: TraceLimitReached) -> dict[str, Any]:
    d = _base_dict(e, "TraceLimitReached")
    d["limit"] = e.limit
    return d


def _cdp_hello_event_to_dict(e: CDPHelloEvent) -> dict[str, Any]:
    d = _base_dict(e, "CDPHelloEvent")
    d["device_id"] = e.device_id
    d["generation"] = e.generation
    return d


# Dispatch map: class → serialiser function.
_SERIALISERS: dict[type, Any] = {
    FrameTransmit: _frame_transmit_to_dict,
    FrameArrival: _frame_arrival_to_dict,
    FrameDropped: _frame_dropped_to_dict,
    ARPRequestSent: _arp_request_sent_to_dict,
    ARPReplySent: _arp_reply_sent_to_dict,
    ARPCacheUpdated: _arp_cache_updated_to_dict,
    MACTableLearned: _mac_table_learned_to_dict,
    ICMPEchoRequestSent: _icmp_echo_request_sent_to_dict,
    ICMPEchoReplySent: _icmp_echo_reply_sent_to_dict,
    TraceLimitReached: _trace_limit_reached_to_dict,
    CDPHelloEvent: _cdp_hello_event_to_dict,
}


# ---------------------------------------------------------------------------
# Per-event-class deserialisers
# ---------------------------------------------------------------------------

def _frame_transmit_from_dict(d: dict[str, Any]) -> FrameTransmit:
    return FrameTransmit(
        time=d["time"], seq=d["seq"],
        device_id=d["device_id"],
        interface_name=d["interface_name"],
        frame=_frame_from_dict(d["frame"]),
    )


def _frame_arrival_from_dict(d: dict[str, Any]) -> FrameArrival:
    return FrameArrival(
        time=d["time"], seq=d["seq"],
        device_id=d["device_id"],
        interface_name=d["interface_name"],
        frame=_frame_from_dict(d["frame"]),
    )


def _frame_dropped_from_dict(d: dict[str, Any]) -> FrameDropped:
    return FrameDropped(
        time=d["time"], seq=d["seq"],
        device_id=d["device_id"],
        interface_name=d.get("interface_name"),
        frame=_frame_from_dict(d["frame"]),
        reason=d["reason"],
    )


def _arp_request_sent_from_dict(d: dict[str, Any]) -> ARPRequestSent:
    return ARPRequestSent(
        time=d["time"], seq=d["seq"],
        device_id=d["device_id"],
        message=_arp_from_dict(d["message"]),
    )


def _arp_reply_sent_from_dict(d: dict[str, Any]) -> ARPReplySent:
    return ARPReplySent(
        time=d["time"], seq=d["seq"],
        device_id=d["device_id"],
        message=_arp_from_dict(d["message"]),
    )


def _arp_cache_updated_from_dict(d: dict[str, Any]) -> ARPCacheUpdated:
    return ARPCacheUpdated(
        time=d["time"], seq=d["seq"],
        device_id=d["device_id"],
        ip_address=d["ip_address"],
        mac_address=d["mac_address"],
    )


def _mac_table_learned_from_dict(d: dict[str, Any]) -> MACTableLearned:
    return MACTableLearned(
        time=d["time"], seq=d["seq"],
        switch_id=d["switch_id"],
        mac_address=d["mac_address"],
        interface_name=d["interface_name"],
        vlan=d["vlan"],
    )


def _icmp_echo_request_sent_from_dict(d: dict[str, Any]) -> ICMPEchoRequestSent:
    return ICMPEchoRequestSent(
        time=d["time"], seq=d["seq"],
        src_device_id=d["src_device_id"],
        dst_device_id=d["dst_device_id"],
        message=_icmp_from_dict(d["message"]),
    )


def _icmp_echo_reply_sent_from_dict(d: dict[str, Any]) -> ICMPEchoReplySent:
    return ICMPEchoReplySent(
        time=d["time"], seq=d["seq"],
        src_device_id=d["src_device_id"],
        dst_device_id=d["dst_device_id"],
        message=_icmp_from_dict(d["message"]),
    )


def _trace_limit_reached_from_dict(d: dict[str, Any]) -> TraceLimitReached:
    return TraceLimitReached(
        time=d["time"], seq=d["seq"],
        limit=d["limit"],
    )


def _cdp_hello_event_from_dict(d: dict[str, Any]) -> CDPHelloEvent:
    return CDPHelloEvent(
        time=d["time"], seq=d["seq"],
        device_id=d["device_id"],
        generation=d["generation"],
    )


_DESERIALISERS: dict[str, Any] = {
    "FrameTransmit": _frame_transmit_from_dict,
    "FrameArrival": _frame_arrival_from_dict,
    "FrameDropped": _frame_dropped_from_dict,
    "ARPRequestSent": _arp_request_sent_from_dict,
    "ARPReplySent": _arp_reply_sent_from_dict,
    "ARPCacheUpdated": _arp_cache_updated_from_dict,
    "MACTableLearned": _mac_table_learned_from_dict,
    "ICMPEchoRequestSent": _icmp_echo_request_sent_from_dict,
    "ICMPEchoReplySent": _icmp_echo_reply_sent_from_dict,
    "TraceLimitReached": _trace_limit_reached_from_dict,
    "CDPHelloEvent": _cdp_hello_event_from_dict,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def trace_to_json(trace: list[SimulationEvent]) -> list[dict[str, Any]]:
    """
    Serialise a list of SimulationEvent objects to a list of JSON-safe dicts.

    Each dict has at minimum: ``"type"``, ``"time"``, ``"seq"``.

    Raises
    ------
    TypeError
        If an event class does not have a registered serialiser.
    """
    result = []
    for event in trace:
        serialiser = _SERIALISERS.get(type(event))
        if serialiser is None:
            raise TypeError(
                f"No serialiser registered for event type "
                f"{type(event).__name__!r}."
            )
        result.append(serialiser(event))
    return result


def trace_from_json(data: list[dict[str, Any]]) -> list[SimulationEvent]:
    """
    Deserialise a list of dicts (as produced by :func:`trace_to_json`) back to
    a list of typed SimulationEvent objects.

    Raises
    ------
    ValueError
        If a dict's ``"type"`` field does not name a known event class.
    KeyError
        If a required field is missing from a dict.
    """
    result = []
    for item in data:
        type_name = item.get("type")
        if not isinstance(type_name, str):
            raise ValueError(f"Event dict has no 'type' field: {item!r}")
        deserialiser = _DESERIALISERS.get(type_name)
        if deserialiser is None:
            raise ValueError(
                f"No deserialiser registered for event type {type_name!r}."
            )
        result.append(deserialiser(item))
    return result
