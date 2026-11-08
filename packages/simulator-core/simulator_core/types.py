"""
simulator_core.types
~~~~~~~~~~~~~~~~~~~~
Shared enums, constants and primitive type aliases used across the simulator.
"""

from __future__ import annotations

from enum import Enum, auto


class InterfaceState(Enum):
    """Administrative and operational state for a device interface or link."""

    UP = auto()
    DOWN = auto()


class DeviceModel(Enum):
    """The device model determines which protocol logic is instantiated."""

    HOST = "host"
    SWITCH = "switch"


# ---------------------------------------------------------------------------
# Simulation timing constants
# ---------------------------------------------------------------------------

#: Number of logical ticks added per link traversal.
#: All links use a uniform propagation delay in this proof-of-concept.
#: A per-link delay model is a future enhancement.
PROPAGATION_DELAY: int = 1

#: Default VLAN for all ports in this proof-of-concept (no 802.1Q trunking).
DEFAULT_VLAN: int = 1
