"""
simulator_core.l2.port_security
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Per-port security state for Catalyst switches (``switchport port-security``).

Secure addresses come in three kinds, as on IOS:

- **SecureConfigured**: ``switchport port-security mac-address H.H.H``
- **SecureSticky**: learned while ``mac-address sticky`` is on; kept in the
  running-config and across link flaps
- **SecureDynamic**: learned otherwise; forgotten when the link goes down
  and subject to ``aging time``

The switch (devices/switch.py) checks every frame received on a secure port
against this state and applies the violation mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SECURE_CONFIGURED = "SecureConfigured"
SECURE_STICKY = "SecureSticky"
SECURE_DYNAMIC = "SecureDynamic"

VIOLATION_MODES = ("protect", "restrict", "shutdown")
MAX_SECURE_ADDRESSES = 132          # Catalyst 2960 per-port limit
SYSTEM_ADDRESS_LIMIT = 4096         # "Max Addresses limit in System"


@dataclass
class SecureAddress:
    kind: str
    learned_at: float = 0.0          # lab seconds
    last_seen: float = 0.0


@dataclass
class PortSecurity:
    enabled: bool = False
    maximum: int = 1
    violation: str = "shutdown"
    sticky: bool = False
    aging_time: int = 0              # minutes; 0 = secure addresses never age
    aging_type: str = "absolute"     # "absolute" | "inactivity"
    addresses: dict[tuple[str, int], SecureAddress] = field(default_factory=dict)
    violation_count: int = 0
    last_source: Optional[tuple[str, int]] = None

    def count(self, kind: Optional[str] = None) -> int:
        return sum(1 for a in self.addresses.values() if kind is None or a.kind == kind)

    def remove_kind(self, kind: str) -> int:
        doomed = [k for k, a in self.addresses.items() if a.kind == kind]
        for k in doomed:
            del self.addresses[k]
        return len(doomed)

    def convert(self, old: str, new: str) -> None:
        for a in self.addresses.values():
            if a.kind == old:
                a.kind = new

    def expired(self, now: float) -> list[tuple[str, int]]:
        """Secure dynamic addresses whose aging time has run out."""
        if self.aging_time <= 0:
            return []
        limit = self.aging_time * 60
        out = []
        for key, a in self.addresses.items():
            if a.kind != SECURE_DYNAMIC:
                continue
            since = a.learned_at if self.aging_type == "absolute" else a.last_seen
            if now - since >= limit:
                out.append(key)
        return out
