"""
simulator_core
~~~~~~~~~~~~~~
NetLab Academy — deterministic discrete-event network simulator core.

This package models a documented subset of Ethernet and IP networking using a
logical clock and a priority-queue event scheduler.  It has zero runtime
dependencies beyond the Python standard library (Python ≥ 3.12).

Public API
----------
Import only from this module or from the explicit sub-modules listed below.
Internal implementation details are subject to change without notice.

Host-I/O isolation guarantee
-----------------------------
The simulator core must never import modules that access host networking,
shell execution or native code.  This is enforced by a test in
tests/test_limits.py (test_no_forbidden_imports) which walks the package's
import graph and asserts that none of its internal modules import socket,
subprocess, ctypes or cffi.

Note: the check runs as a *test*, not at import time, because pytest itself
imports those modules as part of its infrastructure.  Placing the guard at
import time would break the test runner.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Topology construction
# ---------------------------------------------------------------------------
from simulator_core.topology import Topology, Device, Interface, Link
from simulator_core.addresses import MACAddress, IPv4Interface, BROADCAST_MAC, ZERO_MAC
from simulator_core.types import DeviceModel, InterfaceState, PROPAGATION_DELAY, DEFAULT_VLAN

# ---------------------------------------------------------------------------
# Simulation lifecycle
# ---------------------------------------------------------------------------
from simulator_core.simulation import Simulation

# ---------------------------------------------------------------------------
# Device protocol objects
# ---------------------------------------------------------------------------
from simulator_core.devices.host import Host, PingResult, EchoResult
from simulator_core.devices.switch import Switch
from simulator_core.devices.router import Router

# ---------------------------------------------------------------------------
# Events (for trace inspection)
# ---------------------------------------------------------------------------
from simulator_core.events import (
    SimulationEvent,
    FrameArrival,
    FrameTransmit,
    FrameDropped,
    ARPRequestSent,
    ARPReplySent,
    ARPCacheUpdated,
    MACTableLearned,
    ICMPEchoRequestSent,
    ICMPEchoReplySent,
    TraceLimitReached,
    DROP_INTERFACE_ADMIN_DOWN,
    DROP_PORT_DOWN,
    DROP_NO_ROUTE,
    DROP_TTL_EXCEEDED,
    DROP_UNRESOLVABLE_ARP,
    DROP_LINK_DOWN,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
from simulator_core.exceptions import (
    TopologyError,
    ConfigurationError,
    SimulationLimitError,
    UnsupportedCommandError,
)

# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
from simulator_core.serialisation import trace_to_json, trace_from_json

__all__ = [
    # Topology
    "Topology", "Device", "Interface", "Link",
    "MACAddress", "IPv4Interface", "BROADCAST_MAC", "ZERO_MAC",
    "DeviceModel", "InterfaceState", "PROPAGATION_DELAY", "DEFAULT_VLAN",
    # Simulation
    "Simulation",
    # Devices
    "Host", "Switch", "Router", "PingResult", "EchoResult",
    # Events
    "SimulationEvent",
    "FrameArrival", "FrameTransmit", "FrameDropped",
    "ARPRequestSent", "ARPReplySent", "ARPCacheUpdated",
    "MACTableLearned",
    "ICMPEchoRequestSent", "ICMPEchoReplySent",
    "TraceLimitReached",
    # Drop reasons
    "DROP_INTERFACE_ADMIN_DOWN", "DROP_PORT_DOWN", "DROP_NO_ROUTE",
    "DROP_TTL_EXCEEDED", "DROP_UNRESOLVABLE_ARP", "DROP_LINK_DOWN",
    # Exceptions
    "TopologyError", "ConfigurationError", "SimulationLimitError",
    "UnsupportedCommandError",
    # Serialisation
    "trace_to_json", "trace_from_json",
]

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
from simulator_core.cli import CLISession, CLIMode  # noqa: E402
