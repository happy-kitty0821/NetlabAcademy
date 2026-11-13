"""
simulator_core.cdp
~~~~~~~~~~~~~~~~~~
Cisco Discovery Protocol (CDP) state management.

CDPEntry:    Immutable record of a discovered neighbor (one per interface).
CDPManager:  Per-device neighbor table, hello interval, holdtime, enable flag.

No host I/O, no sockets, no eval, no Django.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CDPEntry:
    """
    A single CDP neighbor advertisement received on one local interface.

    All fields come directly from the CDP TLVs of the sender.

    Attributes
    ----------
    device_id:
        The sender's hostname (Device ID TLV).
    local_interface:
        The *sender's* local interface name on which the advertisement
        was sent (Port ID TLV).
    holdtime:
        Seconds before the entry expires without a refresh (default 180).
    capabilities:
        Capability string: "Switch", "Router", or "Host".
    platform:
        Platform string, e.g. "Cisco Catalyst 2960".
    software_version:
        Software version string, e.g. "NetLab Academy Simulator 1.0".
    ip_addresses:
        All configured IP addresses of the sender (tuple for frozen compat).
    native_vlan:
        Native VLAN on the sending interface (default 1).
    duplex:
        Duplex setting: "full", "half", or "auto".
    vtp_domain:
        VTP management domain (empty string if not configured).
    advertisement_version:
        CDP advertisement version (default 2).
    """

    device_id: str
    local_interface: str
    holdtime: int
    capabilities: str
    platform: str
    software_version: str
    ip_addresses: tuple[str, ...]
    native_vlan: int
    duplex: str
    vtp_domain: str
    advertisement_version: int = 2


class CDPManager:
    """
    Per-device CDP neighbor table.

    Attributes
    ----------
    device_id:
        Stable UUID of the owning device.
    hostname:
        Human-readable hostname used as the Device ID TLV.
    capabilities:
        Device capability string sent in outgoing advertisements.
    platform:
        Platform string sent in outgoing advertisements.
    is_enabled:
        Whether CDP is globally enabled on this device.
    hello_interval:
        Ticks (seconds) between successive CDP advertisements.
    holdtime:
        Ticks (seconds) before a neighbor entry expires without a refresh.
    """

    def __init__(
        self,
        device_id: str,
        hostname: str,
        capabilities: str,
        platform: str,
    ) -> None:
        self.device_id: str = device_id
        self.hostname: str = hostname
        self.capabilities: str = capabilities
        self.platform: str = platform
        self.is_enabled: bool = True
        self.hello_interval: int = 60
        self.holdtime: int = 180

        # {local_interface: CDPEntry}  — keyed by the *local* ingress interface
        self._neighbors: dict[str, CDPEntry] = {}
        # {local_interface: last_seen_tick}
        self._last_seen: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Neighbor table mutations
    # ------------------------------------------------------------------

    def update_neighbor(
        self,
        local_interface: str,
        entry: CDPEntry,
        current_tick: int = 0,
    ) -> None:
        """
        Store or refresh a CDP neighbor entry for *local_interface*.

        Parameters
        ----------
        local_interface:
            The local ingress interface on which the CDP frame arrived.
        entry:
            The parsed CDPEntry from the arriving frame.
        current_tick:
            The simulation clock tick at which the entry was received.
        """
        self._neighbors[local_interface] = entry
        self._last_seen[local_interface] = current_tick

    def expire_neighbors(self, current_tick: int) -> list[str]:
        """
        Remove entries whose holdtime has elapsed.

        Returns the list of local interface names whose entries were removed.
        """
        expired = [
            iface
            for iface, last in list(self._last_seen.items())
            if current_tick - last > self._neighbors[iface].holdtime
        ]
        for iface in expired:
            del self._neighbors[iface]
            del self._last_seen[iface]
        return expired

    def get_neighbors(self) -> list[tuple[str, CDPEntry]]:
        """Return all current neighbors as (local_interface, CDPEntry) pairs."""
        return list(self._neighbors.items())

    def get_neighbor(self, local_interface: str) -> Optional[CDPEntry]:
        """Return the CDPEntry for *local_interface*, or None."""
        return self._neighbors.get(local_interface)

    def clear(self) -> None:
        """Remove all neighbor entries."""
        self._neighbors.clear()
        self._last_seen.clear()
