"""
simulator_core.exceptions
~~~~~~~~~~~~~~~~~~~~~~~~~
All custom exception types for the NetLab Academy simulator core.

These are the only exception types that propagate across the simulator's
public API boundary.  Callers should catch these rather than internal
Python built-ins where possible.
"""


class TopologyError(ValueError):
    """
    Raised when a topology description is structurally invalid.

    Examples:
    - Duplicate device or interface IDs.
    - A link whose endpoint references a device or interface that does not exist.
    - A self-link (both endpoints on the same device).
    - Node or link count exceeds the configured maximum.
    """


class ConfigurationError(ValueError):
    """
    Raised when a device or interface configuration value is syntactically or
    semantically invalid *before* any simulation event is scheduled.

    Examples:
    - Malformed IPv4 CIDR string.
    - Address equals the network or broadcast address of its prefix.
    - Duplicate IP address across two interfaces in the same simulation.
    - Attempting to start a ping when the source interface has no IP configured.

    This exception is NOT used for reachability failures that are discovered
    during simulation (e.g. no route to host).  Those are represented as
    PingResult entries with success=False.
    """


class SimulationLimitError(RuntimeError):
    """
    Raised when a configurable resource limit is exceeded.

    Examples:
    - Event queue depth exceeds max_queue.
    - A scheduled event's logical timestamp exceeds max_ticks.

    Raising this exception does NOT corrupt existing simulation state; the
    simulation may be inspected or reset after catching it.
    """


class UnsupportedCommandError(ValueError):
    """
    Raised by the CLI command parser when an input token is not present in the
    supported command allowlist.

    Reserved for the CLI spec (a future feature).  Defined here so that
    simulator_core importers can reference it without importing CLI-layer code.
    """
