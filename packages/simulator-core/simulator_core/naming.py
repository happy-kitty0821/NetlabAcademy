"""
simulator_core.naming
~~~~~~~~~~~~~~~~~~~~~
Interface-name helpers shared by the CLI and the syslog generator.
"""

from __future__ import annotations

import re

# Full IOS interface-type names for the short prefixes the device catalog uses.
LONG_IFACE_TYPE = {
    "fa": "FastEthernet",
    "gi": "GigabitEthernet",
    "te": "TenGigabitEthernet",
    "se": "Serial",
    "po": "Port-channel",
}


def long_name(name: str) -> str:
    """
    IOS full interface name: ``Fa0/1`` → ``FastEthernet0/1``,
    ``Gi0/0.10`` → ``GigabitEthernet0/0.10``.  Names without a known short
    prefix (``Vlan1``, ``Loopback0``, ``eth0``) are returned unchanged.
    """
    m = re.match(r"^([A-Za-z]+)(\d.*)$", name)
    if m and m.group(1).lower() in LONG_IFACE_TYPE:
        return LONG_IFACE_TYPE[m.group(1).lower()] + m.group(2)
    return name
