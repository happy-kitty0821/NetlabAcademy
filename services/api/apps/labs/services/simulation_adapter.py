"""
apps.labs.services.simulation_adapter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bridge between the simulator-core package and the Django API layer.

This module is the ONLY place where simulator-core types are imported
inside Django.  It keeps the adapter contract described in
PROJECT_SPEC.md section 7.3 — the API layer talks to this service,
not directly to simulator_core.

All input from the API is validated here before reaching the simulator.
No arbitrary code or shell execution is ever passed through.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from ipaddress import IPv4Address
from typing import Any

from simulator_core import (
    ConfigurationError,
    Simulation,
    SimulationLimitError,
    TopologyError,
)
from simulator_core.addresses import MACAddress
from simulator_core.devices.host import PingResult
from simulator_core.events import SimulationEvent
from simulator_core.topology import Device, Interface, Link, Topology
from simulator_core.types import DeviceModel, InterfaceState


# ---------------------------------------------------------------------------
# Request / response types (dicts, not Django models — these are API payloads)
# ---------------------------------------------------------------------------

def build_topology_from_document(doc: dict[str, Any]) -> Topology:
    """
    Convert a JSON topology document into a simulator-core Topology.

    Expected document shape:
    {
        "nodes": [
            {
                "id": "host-a",
                "model": "host",          # "host" | "switch"
                "hostname": "PC-A",
                "interfaces": [
                    {"name": "eth0", "mac_seed": 10, "ip": "192.168.1.1/24"}
                ]
            },
            ...
        ],
        "links": [
            {
                "id": "link-1",
                "device_a": "host-a", "interface_a": "eth0",
                "device_b": "switch-1", "interface_b": "Gi0/0"
            },
            ...
        ]
    }

    MAC addresses are generated from a deterministic seed (mac_seed) so
    that the same document always produces the same topology.
    """
    if not isinstance(doc, dict):
        raise ConfigurationError("Topology document must be a JSON object.")

    nodes = doc.get("nodes", [])
    links = doc.get("links", [])

    if not nodes:
        raise ConfigurationError("Topology must have at least one node.")

    topo = Topology()

    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            raise ConfigurationError("Every node must have an 'id'.")

        model_str = node.get("model", "host")
        try:
            model = DeviceModel(model_str)
        except ValueError:
            raise ConfigurationError(
                f"Node {node_id!r} has invalid model {model_str!r}. "
                f"Valid models: {', '.join(m.value for m in DeviceModel)}."
            )
        hostname = node.get("hostname", node_id)
        device = Device(id=str(node_id), model=model, hostname=hostname)

        for iface_data in node.get("interfaces", []):
            iface_name = iface_data.get("name")
            if not iface_name:
                raise ConfigurationError(
                    f"Node {node_id!r} has an interface without a name."
                )

            mac_seed = iface_data.get("mac_seed", hash(iface_name) % 1000)
            mac = MACAddress.generate(random.Random(mac_seed))

            iface = Interface(name=str(iface_name), mac=mac)

            ip_str = iface_data.get("ip")
            if ip_str:
                iface.set_ip(ip_str)

            gateway = iface_data.get("gateway")
            if gateway:
                iface.set_gateway(gateway)

            device.add_interface(iface)

        topo.add_device(device)

    for link_data in links:
        link_id = link_data.get("id")
        if not link_id:
            raise ConfigurationError("Every link must have an 'id'.")

        endpoint_a = (
            str(link_data["device_a"]),
            str(link_data["interface_a"]),
        )
        endpoint_b = (
            str(link_data["device_b"]),
            str(link_data["interface_b"]),
        )
        topo.add_link(Link(id=str(link_id), endpoint_a=endpoint_a, endpoint_b=endpoint_b))

    topo.validate()
    return topo


# ---------------------------------------------------------------------------
# Simulation session manager
# ---------------------------------------------------------------------------

@dataclass
class SimulationSession:
    """
    A live simulation session.  Stored in memory (not the database) for
    this proof-of-concept.  A future iteration may persist these to
    PostgreSQL or Redis.
    """

    id: str
    simulation: Simulation
    topology_doc: dict[str, Any]
    seed: int = 42
    created_at_tick: int = 0

    # Last ping result, if any.
    last_ping: PingResult | None = None

    # CLI sessions keyed by device_id — one per open terminal.
    cli_sessions: dict[str, Any] = field(default_factory=dict)


# In-memory session store.  Keyed by session ID (UUID string).
_sessions: dict[str, SimulationSession] = {}


def create_session(topology_doc: dict[str, Any], seed: int = 42) -> SimulationSession:
    """Create a new simulation session from a topology document."""
    topology = build_topology_from_document(topology_doc)
    sim = Simulation(topology, seed=seed)
    session_id = str(uuid.uuid4())
    session = SimulationSession(
        id=session_id,
        simulation=sim,
        topology_doc=topology_doc,
        seed=seed,
    )
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> SimulationSession:
    """Return an existing session or raise KeyError."""
    try:
        return _sessions[session_id]
    except KeyError:
        raise KeyError(f"Simulation session {session_id!r} not found.")


def delete_session(session_id: str) -> None:
    """Remove a session from memory."""
    _sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def run_ping(session: SimulationSession, device_id: str, target_ip: str,
             count: int = 4) -> dict[str, Any]:
    """
    Issue a ping from a device in the simulation and run the simulation
    to completion.  Returns a JSON-serializable dict with the ping result
    and the event trace.
    """
    sim = session.simulation
    host = sim.get_host(device_id)
    result = host.ping(target_ip, count=count)
    sim.run()
    session.last_ping = result

    return {
        "ping": _ping_result_to_dict(result),
        "trace": _trace_to_list(sim.trace),
    }


def get_device_state(session: SimulationSession, device_id: str) -> dict[str, Any]:
    """Return inspectable state for a device (interfaces, ARP cache, MAC table)."""
    sim = session.simulation
    device = sim.topology.devices.get(device_id)
    if device is None:
        raise KeyError(f"Device {device_id!r} not found.")

    state: dict[str, Any] = {
        "id": device.id,
        "hostname": device.hostname,
        "model": device.model.value,
        "interfaces": {},
    }

    for name, iface in device.interfaces.items():
        state["interfaces"][name] = {
            "name": name,
            "mac": iface.mac.value,
            "admin_state": iface.admin_state.name,
            "oper_state": iface.oper_state.name,
            "ip": str(iface.ip_config) if iface.ip_config else None,
            "gateway": iface.default_gateway,
            "rx_frames": iface.rx_frames,
            "tx_frames": iface.tx_frames,
        }

    # Add protocol-specific state.
    if device.model == DeviceModel.HOST:
        host = sim.get_host(device_id)
        state["arp_cache"] = {
            str(ip): mac.value for ip, mac in host.arp_cache.items()
        }
    elif device.model == DeviceModel.SWITCH:
        switch = sim.get_switch(device_id)
        state["mac_table"] = [
            {"mac": mac, "vlan": vlan, "interface": iface}
            for (mac, vlan), iface in switch.mac_table.items()
        ]
        state["vlans"] = [
            {"id": vid, "name": vname}
            for vid, vname in switch.vlans.items()
        ]
    elif device.model == DeviceModel.ROUTER:
        router = sim.get_router(device_id)
        state["arp_cache"] = {
            str(ip): mac.value for ip, mac in router.arp_cache.items()
        }
        state["routing_table"] = [
            {
                "network": str(r.network),
                "next_hop": str(r.next_hop) if r.next_hop else "connected",
                "interface": r.outgoing_interface,
                "source": r.source.name.lower(),
                "metric": r.metric,
            }
            for r in router.routing_table.routes
        ]

    return state


def get_trace(session: SimulationSession) -> list[dict[str, Any]]:
    """Return the full event trace as a list of JSON dicts."""
    return _trace_to_list(session.simulation.trace)


def reset_session(session: SimulationSession) -> dict[str, Any]:
    """Reset the simulation to its initial state."""
    session.simulation.reset()
    return {
        "clock": session.simulation.clock,
        "trace": [],
    }


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _ping_result_to_dict(result: PingResult) -> dict[str, Any]:
    return {
        "target_ip": result.target_ip,
        "count": result.count,
        "sent": result.sent,
        "received": result.received,
        "results": [
            {
                "sequence": r.sequence,
                "success": r.success,
                "rtt_ticks": r.rtt_ticks,
                "drop_reason": r.drop_reason,
            }
            for r in result.results
        ],
    }


def _trace_to_list(trace: list[SimulationEvent]) -> list[dict[str, Any]]:
    """Convert a list of typed events to a list of JSON-safe dicts."""
    items: list[dict[str, Any]] = []
    for event in trace:
        entry: dict[str, Any] = {
            "type": type(event).__name__,
            "time": event.time,
            "seq": event.seq,
        }
        # Extract key fields without dumping the entire dataclass.
        for attr in ("device_id", "switch_id", "interface_name", "reason",
                      "mac_address", "ip_address", "vlan", "src_device_id",
                      "dst_device_id", "limit"):
            val = getattr(event, attr, None)
            if val is not None:
                entry[attr] = str(val) if not isinstance(val, (int, str, bool)) else val

        # Extract message metadata for ARP/ICMP events.
        msg = getattr(event, "message", None)
        if msg is not None:
            entry["message_type"] = type(msg).__name__
            if hasattr(msg, "operation"):
                entry["operation"] = "request" if msg.operation == 1 else "reply"
                entry["sender_ip"] = str(msg.sender_ip)
                entry["target_ip"] = str(msg.target_ip)
            if hasattr(msg, "type"):
                entry["icmp_type"] = "echo_request" if msg.type == 8 else "echo_reply"
                entry["sequence"] = msg.sequence

        items.append(entry)
    return items


def get_or_create_cli_session(session: SimulationSession, device_id: str):
    """
    Return the existing CLISession for *device_id* in *session*, or
    create a new one.  Raises KeyError if *device_id* does not exist.
    """
    if device_id not in session.simulation.topology.devices:
        raise KeyError(f"Device {device_id!r} not found in simulation.")

    if device_id not in session.cli_sessions:
        from simulator_core.cli import CLISession
        session.cli_sessions[device_id] = CLISession(
            device_id=device_id,
            simulation=session.simulation,
        )
    return session.cli_sessions[device_id]
