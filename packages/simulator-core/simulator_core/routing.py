"""
simulator_core.routing
~~~~~~~~~~~~~~~~~~~~~~
IPv4 routing table with longest-prefix match.

Supports two route sources:
  - CONNECTED: automatically created when an interface has an IP address.
  - STATIC:    manually added via CLI `ip route` command.

Route selection: longest-prefix match wins. Ties broken by lower metric.

No host I/O, no sockets, no subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from ipaddress import IPv4Address, IPv4Network
from typing import Optional


class RouteSource(Enum):
    CONNECTED = auto()
    STATIC   = auto()
    # Future: OSPF, BGP, etc.


@dataclass
class RouteEntry:
    """
    One entry in the routing table.

    Attributes
    ----------
    network:
        The destination IPv4Network (e.g. 192.168.1.0/24).
    next_hop:
        The gateway IP to forward to.  None for directly connected routes
        (the destination IS the local subnet).
    outgoing_interface:
        The interface name to send the packet out of.
    source:
        How this route was learned (connected, static, etc.).
    metric:
        Administrative distance / metric.  Lower is preferred.
    """

    network: IPv4Network
    next_hop: Optional[IPv4Address]
    outgoing_interface: str
    source: RouteSource = RouteSource.CONNECTED
    metric: int = 0

    @property
    def prefix_length(self) -> int:
        return self.network.prefixlen

    def __str__(self) -> str:
        nh = str(self.next_hop) if self.next_hop else "directly connected"
        return f"{self.network} via {nh} on {self.outgoing_interface} ({self.source.name.lower()})"


class RoutingTable:
    """
    IPv4 routing table with longest-prefix match.

    Usage:
        rt = RoutingTable()
        rt.add_connected_route(IPv4Network("192.168.1.0/24"), "eth0")
        rt.add_static_route(IPv4Network("10.0.0.0/8"), IPv4Address("192.168.1.254"), "eth0")
        entry = rt.lookup(IPv4Address("10.0.0.1"))
    """

    def __init__(self) -> None:
        self._routes: list[RouteEntry] = []

    # ------------------------------------------------------------------
    # Adding routes
    # ------------------------------------------------------------------

    def add_connected_route(self, network: IPv4Network, interface: str) -> None:
        """Add a directly connected route (created automatically)."""
        # Remove any existing connected route for the same network
        self._routes = [
            r for r in self._routes
            if not (r.network == network and r.source == RouteSource.CONNECTED)
        ]
        self._routes.append(RouteEntry(
            network=network,
            next_hop=None,
            outgoing_interface=interface,
            source=RouteSource.CONNECTED,
            metric=0,
        ))

    def add_static_route(
        self,
        network: IPv4Network,
        next_hop: IPv4Address,
        interface: str,
        metric: int = 1,
    ) -> None:
        """Add or replace a static route."""
        # Remove any existing static route for the same network
        self._routes = [
            r for r in self._routes
            if not (r.network == network and r.source == RouteSource.STATIC)
        ]
        self._routes.append(RouteEntry(
            network=network,
            next_hop=next_hop,
            outgoing_interface=interface,
            source=RouteSource.STATIC,
            metric=metric,
        ))

    def remove_static_route(self, network: IPv4Network) -> bool:
        """Remove a static route. Returns True if found and removed."""
        before = len(self._routes)
        self._routes = [
            r for r in self._routes
            if not (r.network == network and r.source == RouteSource.STATIC)
        ]
        return len(self._routes) < before

    def remove_interface_routes(self, interface: str) -> None:
        """Remove all routes associated with an interface (when it goes down)."""
        self._routes = [r for r in self._routes if r.outgoing_interface != interface]

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, destination: IPv4Address) -> Optional[RouteEntry]:
        """
        Find the best route for *destination* using longest-prefix match.

        Returns None if no route exists.
        """
        candidates = [
            r for r in self._routes
            if destination in r.network
        ]
        if not candidates:
            return None

        # Longest prefix match
        max_prefix = max(r.prefix_length for r in candidates)
        best = [r for r in candidates if r.prefix_length == max_prefix]

        # Lowest metric wins
        best.sort(key=lambda r: r.metric)
        return best[0]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def routes(self) -> list[RouteEntry]:
        """All routes, sorted by prefix length (longest first)."""
        return sorted(self._routes, key=lambda r: (-r.prefix_length, r.metric))

    def __len__(self) -> int:
        return len(self._routes)

    def __bool__(self) -> bool:
        return len(self._routes) > 0
