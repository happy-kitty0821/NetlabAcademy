"""
simulator_core.addresses
~~~~~~~~~~~~~~~~~~~~~~~~
Primitive address types used throughout the simulator.

Both types are immutable (frozen dataclasses) and carry their own validation
so that invalid addresses can never propagate into the event model.

No host I/O, no socket imports.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network

from simulator_core.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAC_PATTERN = re.compile(
    r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$",
    re.IGNORECASE,
)

BROADCAST_MAC_VALUE = "ff:ff:ff:ff:ff:ff"

# ---------------------------------------------------------------------------
# MACAddress
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MACAddress:
    """
    48-bit Ethernet MAC address stored as a normalised lowercase colon-hex string.

    Examples
    --------
    >>> MACAddress("aa:bb:cc:dd:ee:ff")
    MACAddress(value='aa:bb:cc:dd:ee:ff')
    >>> MACAddress.generate(random.Random(42))
    MACAddress(value=...)
    """

    value: str  # e.g. "aa:bb:cc:dd:ee:ff"

    def __post_init__(self) -> None:
        normalised = self.value.lower()
        # Use object.__setattr__ because the dataclass is frozen.
        object.__setattr__(self, "value", normalised)
        if not _MAC_PATTERN.match(normalised):
            raise ConfigurationError(
                f"Invalid MAC address {self.value!r}: expected 6 colon-separated "
                f"hex octets, e.g. 'aa:bb:cc:dd:ee:ff'."
            )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def generate(rng: random.Random) -> "MACAddress":
        """
        Generate a locally-administered, unicast MAC address using *rng*.

        Bit semantics of the first octet:
        - Bit 0 (LSB): 0 = unicast  (we clear this bit).
        - Bit 1:       1 = locally administered  (we set this bit).

        Using the simulation-owned RNG ensures deterministic MAC generation
        when the same seed is used — critical for replay tests.
        """
        octets = [rng.randint(0, 255) for _ in range(6)]
        # First octet: clear unicast bit (0), set locally-administered bit (1).
        octets[0] = (octets[0] & 0xFE) | 0x02
        return MACAddress(":".join(f"{b:02x}" for b in octets))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_broadcast(self) -> bool:
        """True iff this is the Ethernet broadcast address FF:FF:FF:FF:FF:FF."""
        return self.value == BROADCAST_MAC_VALUE

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"MACAddress(value={self.value!r})"


# Singleton broadcast MAC for convenience.
BROADCAST_MAC = MACAddress(BROADCAST_MAC_VALUE)
ZERO_MAC = MACAddress("00:00:00:00:00:00")

# ---------------------------------------------------------------------------
# IPv4Interface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IPv4Interface:
    """
    An IPv4 address bound to a prefix length, representing a host address
    on a subnet (not a network or broadcast address).

    Examples
    --------
    >>> IPv4Interface.parse("192.168.1.1/24")
    IPv4Interface(address=IPv4Address('192.168.1.1'), prefix_length=24)
    """

    address: IPv4Address
    prefix_length: int  # 0–32

    def __post_init__(self) -> None:
        if not (0 <= self.prefix_length <= 32):
            raise ConfigurationError(
                f"Prefix length {self.prefix_length} is out of range 0–32."
            )
        if not self.is_host_address:
            raise ConfigurationError(
                f"{self.address}/{self.prefix_length} is not a valid host address: "
                f"it is either the network address ({self.network.network_address}) "
                f"or the broadcast address ({self.broadcast})."
            )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def parse(cidr: str) -> "IPv4Interface":
        """
        Parse a CIDR string such as '192.168.1.1/24'.

        Raises ConfigurationError for:
        - Strings that do not match 'A.B.C.D/N' format.
        - Prefix lengths outside 0–32.
        - Addresses that are the network or broadcast address of their prefix.
        """
        if "/" not in cidr:
            raise ConfigurationError(
                f"Invalid CIDR {cidr!r}: expected format 'A.B.C.D/N'."
            )
        addr_str, prefix_str = cidr.split("/", 1)
        try:
            prefix_length = int(prefix_str)
        except ValueError:
            raise ConfigurationError(
                f"Invalid prefix length in {cidr!r}: {prefix_str!r} is not an integer."
            )
        try:
            address = IPv4Address(addr_str)
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid IPv4 address in {cidr!r}: {exc}"
            ) from exc
        # Validation happens in __post_init__.
        return IPv4Interface(address=address, prefix_length=prefix_length)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def network(self) -> IPv4Network:
        """The IPv4 network this address belongs to (host bits masked)."""
        return IPv4Network(f"{self.address}/{self.prefix_length}", strict=False)

    @property
    def broadcast(self) -> IPv4Address:
        """The broadcast address of this interface's network."""
        return self.network.broadcast_address

    @property
    def network_address(self) -> IPv4Address:
        """The network address (all host bits zero)."""
        return self.network.network_address

    @property
    def is_host_address(self) -> bool:
        """
        True iff the address is neither the network address nor the broadcast address
        of its prefix.  A /32 address is always a host address (no broadcast concept).
        """
        if self.prefix_length == 32:
            return True
        net = IPv4Network(f"{self.address}/{self.prefix_length}", strict=False)
        return (
            self.address != net.network_address
            and self.address != net.broadcast_address
        )

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.address}/{self.prefix_length}"

    def __repr__(self) -> str:
        return f"IPv4Interface(address={self.address!r}, prefix_length={self.prefix_length})"
