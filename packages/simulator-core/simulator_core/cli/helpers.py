"""
Interface naming, status words and formatting helpers shared by the
command modules.
"""

from __future__ import annotations

import re
from ipaddress import IPv4Address
from typing import Optional

from simulator_core.naming import LONG_IFACE_TYPE as _LONG_IFACE_TYPE, long_name as _long_name
from simulator_core.types import InterfaceState


def _speed_to_stp_cost(speed_kbps: int) -> int:
    """Map a link speed (Kbps) to an STP path cost (short method)."""
    if speed_kbps <= 10_000:
        return 100
    if speed_kbps <= 100_000:
        return 19
    if speed_kbps <= 1_000_000:
        return 4
    return 2


def _status_words(iface) -> tuple[str, str]:
    """IOS (status, protocol) words for an interface."""
    if iface.admin_state == InterfaceState.DOWN:
        return "administratively down", "down"
    if iface.oper_state == InterfaceState.UP:
        return "up", "up"
    return "down", "down"


# Full IOS type keyword for each interface-name type prefix used by the
# device catalog.  A user-typed type is accepted when it is a prefix of the
# full keyword ("f", "fa", "fast", "FastEthernet" all select "Fa" ports).
_IFACE_TYPE_FULL = {
    "fa": "fastethernet",
    "gi": "gigabitethernet",
    "te": "tengigabitethernet",
    "eth": "ethernet",
    "e": "ethernet",
    "se": "serial",
    "po": "port-channel",
    "loopback": "loopback",
    "vlan": "vlan",
}


_IFACE_NAME_RE = re.compile(r"^([A-Za-z][A-Za-z-]*)\s*(\d[\d/.:]*)$")


def _dtp_mode_word(iface) -> str:
    """The Mode column of ``show interfaces trunk``."""
    if iface.switchport_mode == "dynamic_desirable":
        return "desirable"
    if iface.switchport_mode == "dynamic_auto":
        return "auto"
    return "nonegotiate" if iface.dtp_nonegotiate else "on"


def _mask_prefix(mask_int: int) -> Optional[int]:
    """Prefix length of a contiguous dotted mask, or None if non-contiguous."""
    inverted = (~mask_int) & 0xFFFFFFFF
    if inverted & (inverted + 1):
        return None
    return 32 - inverted.bit_length()


def _is_valid_host_address(ip: IPv4Address) -> bool:
    """IOS rejects loopback, 0.x, multicast and class E as interface addresses."""
    first = int(ip) >> 24
    return not (first == 0 or first == 127 or first >= 224)


def _display_order(device) -> list[str]:
    """
    IOS listing order: physical ports in hardware order, each followed by
    its subinterfaces, then loopbacks and SVIs in numeric order.
    """
    names = list(device.interfaces)
    physical = [n for n in names if "." not in n
                and not n.lower().startswith(("vlan", "loopback"))]
    order: list[str] = []
    for n in physical:
        order.append(n)
        subs = [s for s in names if s.startswith(n + ".")]
        order += sorted(subs, key=lambda x: int(x.rsplit(".", 1)[1]))
    rest = [n for n in names if n not in order]
    order += sorted(rest, key=_natural_key)
    return order


def _natural_key(name: str) -> tuple:
    """Sort Fa0/2 before Fa0/10."""
    return tuple(int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name))


def _hardware_name(name: str) -> str:
    low = name.lower()
    for prefix, hw in (("fa", "Fast Ethernet"), ("gi", "Gigabit Ethernet"),
                       ("te", "Ten Gigabit Ethernet"), ("vlan", "EtherSVI"),
                       ("loopback", "Loopback"), ("po", "EtherChannel")):
        if low.startswith(prefix):
            return hw
    return "Ethernet"


def _media_type(name: str) -> str:
    low = name.lower()
    if low.startswith("gi"):
        return "10/100/1000BaseTX"
    if low.startswith("te"):
        return "10GBase-SR"
    return "10/100BaseTX"


def _switch_port_status(iface, vlans=None) -> str:
    """
    show interfaces status word: connected / notconnect / disabled, or
    inactive for an access port whose VLAN is not in the VLAN database.
    """
    if iface.admin_state == InterfaceState.DOWN:
        return "disabled"
    if getattr(iface, "err_disabled", None):
        return "err-disabled"
    if vlans is not None and iface.is_access and iface.vlan not in vlans:
        return "inactive"
    if iface.oper_state == InterfaceState.UP:
        return "connected"
    return "notconnect"


def _cisco_mac(mac) -> str:
    """Cisco dotted MAC notation: ``aa:bb:cc:dd:ee:ff`` → ``aabb.ccdd.eeff``."""
    raw = str(getattr(mac, "value", mac)).replace(":", "").replace("-", "").replace(".", "").lower()
    if len(raw) != 12:
        return str(mac)
    return f"{raw[0:4]}.{raw[4:8]}.{raw[8:12]}"


def _virtual_iface_mac(device_id: str, iface_name: str):
    """
    Stable MAC for an interface created from the CLI (SVI, loopback,
    subinterface).  Derived from a digest so a replayed lab gets the same
    address in every process (Python's hash() is randomised per process).
    """
    import hashlib
    import random
    from simulator_core.addresses import MACAddress
    seed = int(hashlib.md5(f"{device_id}/{iface_name}".encode()).hexdigest(), 16) % (2 ** 31)
    return MACAddress.generate(random.Random(seed))


def _split_iface_name(name: str) -> Optional[tuple[str, str]]:
    """Split ``"Fa0/1"`` into ``("fa", "0/1")``; None if not type+number."""
    m = _IFACE_NAME_RE.match(name.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2)


def _match_iface(input_name: str, iface_names: list[str]) -> list[str]:
    """
    Match a user-typed interface name against the device's interfaces.

    IOS rules: the interface *type* may be abbreviated to any unambiguous
    prefix of its full keyword, but the *number* must match exactly.

    - ``fa0/1``, ``f0/1``, ``FastEthernet0/1`` → ``Fa0/1``
    - ``g0/1`` on a FastEthernet-only switch → no match (wrong type)
    - ``fa0/1.10`` → no match (subinterfaces are not modelled)
    - ``0/1`` → no match (a type is required)

    Returns every matching interface name; more than one means the typed
    type prefix is ambiguous on this device.
    """
    lower_input = input_name.strip().lower()

    exact = [n for n in iface_names if n.lower() == lower_input]
    if exact:
        return exact

    parsed = _split_iface_name(input_name)
    if parsed is None:
        return []
    typed_type, typed_number = parsed

    matches = []
    for name in iface_names:
        own = _split_iface_name(name)
        if own is None:
            continue
        own_type, own_number = own
        if own_number != typed_number:
            continue
        full_type = _IFACE_TYPE_FULL.get(own_type, own_type)
        if typed_type == own_type or full_type.startswith(typed_type):
            matches.append(name)
    return matches


def _join_iface_tokens(tokens: list[str], idx: int) -> list[str]:
    """
    Collapse IOS's spaced interface form (``FastEthernet 0/1``) at
    ``tokens[idx]`` into a single token (``FastEthernet0/1``).
    """
    if (len(tokens) > idx + 1 and tokens[idx].isalpha()
            and tokens[idx + 1][:1].isdigit()):
        return tokens[:idx] + [tokens[idx] + tokens[idx + 1]] + tokens[idx + 2:]
    return tokens


def _expand_iface_range(spec: str, iface_names: list[str]) -> tuple[list[str], Optional[str]]:
    """
    Expand an ``interface range`` specification into interface names.

    Accepts comma-separated segments, each ``<type><slot>/<first>[ - <last>]``,
    e.g. ``fa0/1 - 5``, ``fa0/1-5``, ``f0/1 - 2 , f0/5``.

    Returns (names, None) on success or ([], error-message) on failure.
    """
    seg_re = re.compile(
        r"^([A-Za-z][A-Za-z-]*)\s*((?:\d+/)*)(\d+)\s*(?:-\s*(\d+))?$"
    )
    result: list[str] = []
    for segment in spec.split(","):
        segment = segment.strip()
        m = seg_re.match(segment)
        if not m:
            return [], f"% Invalid interface range: {segment!r}"
        typ, slot, first, last = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        last_i = int(last) if last is not None else first
        if last_i < first:
            return [], f"% Invalid interface range: {segment!r}"
        for port in range(first, last_i + 1):
            typed = f"{typ}{slot}{port}"
            found = _match_iface(typed, iface_names)
            if len(found) != 1:
                return [], f"% Invalid interface name: {typed!r}"
            if found[0] not in result:
                result.append(found[0])
    return result, None
