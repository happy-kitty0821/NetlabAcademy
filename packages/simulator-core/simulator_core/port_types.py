"""
simulator_core.port_types
~~~~~~~~~~~~~~~~~~~~~~~~~
Port type definitions and speed/cost calculations.

Cisco IOS interface naming and capabilities:
  Ethernet (10 Mbps)        — names start with "Eth" or "e"
  Fast Ethernet (100 Mbps)  — names start with "FastEthernet" or "Fa"
  Gigabit Ethernet (1 Gbps) — names start with "GigabitEthernet" or "Gi"
  Ten Gigabit (10 Gbps)     — names start with "TenGigabitEthernet" or "Te"
  Loopback (virtual)        — names start with "Loopback" or "Lo"
  Vlan (SVI, virtual)       — names start with "Vlan" or "Vl"

STP path cost (IEEE 802.1D-1998 short method):
  10 Mbps  = 100
  100 Mbps = 19
  1 Gbps   = 4
  10 Gbps  = 2

STP path cost (IEEE 802.1D-2004 long method):
  10 Mbps  = 2,000,000
  100 Mbps = 200,000
  1 Gbps   = 20,000
  10 Gbps  = 2,000
"""

from __future__ import annotations

from enum import Enum


class PortType(Enum):
    """Interface media type."""
    ETHERNET        = "ethernet"
    FAST_ETHERNET   = "fastethernet"
    GIGABIT_ETHERNET = "gigabitethernet"
    TEN_GIGABIT     = "tengigabitethernet"
    LOOPBACK        = "loopback"
    SVI             = "svi"           # Switch Virtual Interface (Vlan)
    PORT_CHANNEL    = "port-channel"

    @property
    def speed_kbps(self) -> int:
        """Default speed in Kbps for this port type."""
        return _SPEED_MAP.get(self, 1_000_000)

    @property
    def stp_cost_short(self) -> int:
        """STP path cost (short method, 802.1D-1998)."""
        return _STP_COST_SHORT.get(self, 19)

    @property
    def stp_cost_long(self) -> int:
        """STP path cost (long method, 802.1D-2004)."""
        return _STP_COST_LONG.get(self, 20_000)

    @property
    def cisco_prefix(self) -> str:
        """Cisco IOS interface name prefix."""
        return _CISCO_PREFIX.get(self, "Gi")

    @property
    def short_prefix(self) -> str:
        """Cisco IOS short abbreviation."""
        return _SHORT_PREFIX.get(self, "Gi")

    @property
    def is_physical(self) -> bool:
        """True if this is a physical port (not loopback/SVI/port-channel)."""
        return self in (
            PortType.ETHERNET,
            PortType.FAST_ETHERNET,
            PortType.GIGABIT_ETHERNET,
            PortType.TEN_GIGABIT,
        )

    @property
    def supports_switchport(self) -> bool:
        """True if this port can be configured as a switchport (L2)."""
        return self.is_physical

    @property
    def supports_routing(self) -> bool:
        """True if this port can be converted to a routed port (L3)."""
        return self.is_physical


# ── Speed lookup (Kbps) ─────────────────────────────────────────────────────────

_SPEED_MAP: dict[PortType, int] = {
    PortType.ETHERNET:          10_000,        # 10 Mbps
    PortType.FAST_ETHERNET:     100_000,       # 100 Mbps
    PortType.GIGABIT_ETHERNET:  1_000_000,     # 1 Gbps
    PortType.TEN_GIGABIT:       10_000_000,    # 10 Gbps
    PortType.LOOPBACK:          0,             # virtual
    PortType.SVI:               0,             # virtual
    PortType.PORT_CHANNEL:      1_000_000,     # depends on members; default 1G
}


# ── STP path cost (short method, 802.1D-1998) ──────────────────────────────────

_STP_COST_SHORT: dict[PortType, int] = {
    PortType.ETHERNET:          100,
    PortType.FAST_ETHERNET:     19,
    PortType.GIGABIT_ETHERNET:  4,
    PortType.TEN_GIGABIT:       2,
    PortType.LOOPBACK:          0,
    PortType.SVI:               0,
    PortType.PORT_CHANNEL:      4,   # default to gigabit
}


# ── STP path cost (long method, 802.1D-2004) ──────────────────────────────────

_STP_COST_LONG: dict[PortType, int] = {
    PortType.ETHERNET:          2_000_000,
    PortType.FAST_ETHERNET:     200_000,
    PortType.GIGABIT_ETHERNET:  20_000,
    PortType.TEN_GIGABIT:      2_000,
    PortType.LOOPBACK:          0,
    PortType.SVI:               0,
    PortType.PORT_CHANNEL:      20_000,
}


# ── Cisco IOS name prefixes ────────────────────────────────────────────────────

_CISCO_PREFIX: dict[PortType, str] = {
    PortType.ETHERNET:          "Ethernet",
    PortType.FAST_ETHERNET:     "FastEthernet",
    PortType.GIGABIT_ETHERNET:  "GigabitEthernet",
    PortType.TEN_GIGABIT:       "TenGigabitEthernet",
    PortType.LOOPBACK:          "Loopback",
    PortType.SVI:               "Vlan",
    PortType.PORT_CHANNEL:      "Port-channel",
}

_SHORT_PREFIX: dict[PortType, str] = {
    PortType.ETHERNET:          "Eth",
    PortType.FAST_ETHERNET:     "Fa",
    PortType.GIGABIT_ETHERNET:  "Gi",
    PortType.TEN_GIGABIT:       "Te",
    PortType.LOOPBACK:          "Lo",
    PortType.SVI:               "Vl",
    PortType.PORT_CHANNEL:      "Po",
}


# ── Name parsing ───────────────────────────────────────────────────────────────

def detect_port_type(name: str) -> PortType:
    """
    Detect the port type from a Cisco-style interface name.

    Examples:
      "GigabitEthernet0/0" → GIGABIT_ETHERNET
      "Gi0/0"              → GIGABIT_ETHERNET
      "Fa0/1"              → FAST_ETHERNET
      "FastEthernet0/1"    → FAST_ETHERNET
      "eth0"               → ETHERNET
      "Loopback0"          → LOOPBACK
      "Vlan10"             → SVI
      "Port-channel1"     → PORT_CHANNEL
    """
    lower = name.lower()

    # Order matters — check longer prefixes first
    if lower.startswith("tengigabitethernet") or lower.startswith("te"):
        return PortType.TEN_GIGABIT
    if lower.startswith("gigabitethernet") or lower.startswith("gi"):
        return PortType.GIGABIT_ETHERNET
    if lower.startswith("fastethernet") or lower.startswith("fa"):
        return PortType.FAST_ETHERNET
    if lower.startswith("ethernet") or lower.startswith("eth") or lower.startswith("e0"):
        return PortType.ETHERNET
    if lower.startswith("loopback") or lower.startswith("lo"):
        return PortType.LOOPBACK
    if lower.startswith("vlan") or lower.startswith("vl"):
        return PortType.SVI
    if lower.startswith("port-channel") or lower.startswith("po"):
        return PortType.PORT_CHANNEL

    # Default: assume gigabit
    return PortType.GIGABIT_ETHERNET


def format_speed(speed_kbps: int) -> str:
    """Format speed in human-readable form for show commands."""
    if speed_kbps >= 1_000_000:
        return f"{speed_kbps // 1_000_000}Gbps"
    if speed_kbps >= 1_000:
        return f"{speed_kbps // 1_000}Mbps"
    return f"{speed_kbps}Kbps"
