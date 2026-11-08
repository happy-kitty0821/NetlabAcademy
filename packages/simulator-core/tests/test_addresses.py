"""
tests/test_addresses.py
-----------------------
Unit tests for MACAddress and IPv4Interface.

Covers: valid construction, normalisation, validation errors, MAC generation
determinism, broadcast detection, CIDR parsing and host-address checks.
"""

from __future__ import annotations

import random

import pytest

from simulator_core.addresses import (
    BROADCAST_MAC,
    BROADCAST_MAC_VALUE,
    ZERO_MAC,
    IPv4Interface,
    MACAddress,
)
from simulator_core.exceptions import ConfigurationError


# =============================================================================
# MACAddress
# =============================================================================


class TestMACAddressConstruction:
    def test_valid_lowercase(self) -> None:
        mac = MACAddress("aa:bb:cc:dd:ee:ff")
        assert mac.value == "aa:bb:cc:dd:ee:ff"

    def test_valid_uppercase_normalised(self) -> None:
        mac = MACAddress("AA:BB:CC:DD:EE:FF")
        assert mac.value == "aa:bb:cc:dd:ee:ff"

    def test_valid_mixed_case_normalised(self) -> None:
        mac = MACAddress("Aa:Bb:Cc:Dd:Ee:Ff")
        assert mac.value == "aa:bb:cc:dd:ee:ff"

    def test_broadcast_construction_allowed(self) -> None:
        # Broadcast is a valid MAC value; is_broadcast check is at usage time.
        mac = MACAddress(BROADCAST_MAC_VALUE)
        assert mac.is_broadcast

    def test_zero_mac(self) -> None:
        mac = ZERO_MAC
        assert mac.value == "00:00:00:00:00:00"
        assert not mac.is_broadcast

    def test_string_repr(self) -> None:
        mac = MACAddress("11:22:33:44:55:66")
        assert str(mac) == "11:22:33:44:55:66"

    def test_frozen_immutable(self) -> None:
        mac = MACAddress("aa:bb:cc:dd:ee:ff")
        with pytest.raises((AttributeError, TypeError)):
            mac.value = "00:00:00:00:00:00"  # type: ignore[misc]


class TestMACAddressValidation:
    def test_wrong_octet_count_short(self) -> None:
        with pytest.raises(ConfigurationError):
            MACAddress("aa:bb:cc:dd:ee")

    def test_wrong_octet_count_long(self) -> None:
        with pytest.raises(ConfigurationError):
            MACAddress("aa:bb:cc:dd:ee:ff:00")

    def test_non_hex_octet(self) -> None:
        with pytest.raises(ConfigurationError):
            MACAddress("gg:bb:cc:dd:ee:ff")

    def test_wrong_separator(self) -> None:
        with pytest.raises(ConfigurationError):
            MACAddress("aa-bb-cc-dd-ee-ff")

    def test_empty_string(self) -> None:
        with pytest.raises(ConfigurationError):
            MACAddress("")

    def test_spaces_not_allowed(self) -> None:
        with pytest.raises(ConfigurationError):
            MACAddress("aa:bb:cc:dd:ee: f")


class TestMACAddressGeneration:
    def test_generate_returns_mac_address(self) -> None:
        rng = random.Random(42)
        mac = MACAddress.generate(rng)
        assert isinstance(mac, MACAddress)

    def test_generated_mac_is_unicast(self) -> None:
        rng = random.Random(42)
        mac = MACAddress.generate(rng)
        first_octet = int(mac.value.split(":")[0], 16)
        # Bit 0 of first octet must be 0 (unicast).
        assert (first_octet & 0x01) == 0

    def test_generated_mac_is_locally_administered(self) -> None:
        rng = random.Random(42)
        mac = MACAddress.generate(rng)
        first_octet = int(mac.value.split(":")[0], 16)
        # Bit 1 of first octet must be 1 (locally administered).
        assert (first_octet & 0x02) == 0x02

    def test_generate_deterministic_same_seed(self) -> None:
        mac1 = MACAddress.generate(random.Random(42))
        mac2 = MACAddress.generate(random.Random(42))
        assert mac1 == mac2

    def test_generate_different_seed_usually_different(self) -> None:
        mac1 = MACAddress.generate(random.Random(1))
        mac2 = MACAddress.generate(random.Random(2))
        # Different seeds should produce different MACs with overwhelming probability.
        assert mac1 != mac2

    def test_generate_sequential_calls_different(self) -> None:
        rng = random.Random(42)
        mac1 = MACAddress.generate(rng)
        mac2 = MACAddress.generate(rng)
        assert mac1 != mac2

    def test_generated_is_not_broadcast(self) -> None:
        for seed in range(20):
            mac = MACAddress.generate(random.Random(seed))
            assert not mac.is_broadcast


class TestMACAddressBroadcast:
    def test_broadcast_singleton(self) -> None:
        assert BROADCAST_MAC.is_broadcast
        assert BROADCAST_MAC.value == BROADCAST_MAC_VALUE

    def test_non_broadcast(self) -> None:
        mac = MACAddress("aa:bb:cc:dd:ee:ff")
        assert not mac.is_broadcast


# =============================================================================
# IPv4Interface
# =============================================================================


class TestIPv4InterfaceParse:
    def test_valid_host_address(self) -> None:
        iface = IPv4Interface.parse("192.168.1.1/24")
        assert str(iface.address) == "192.168.1.1"
        assert iface.prefix_length == 24

    def test_valid_class_b(self) -> None:
        iface = IPv4Interface.parse("10.0.0.1/16")
        assert iface.prefix_length == 16

    def test_valid_slash32(self) -> None:
        iface = IPv4Interface.parse("192.168.1.1/32")
        assert iface.prefix_length == 32

    def test_string_representation(self) -> None:
        iface = IPv4Interface.parse("10.1.2.3/24")
        assert str(iface) == "10.1.2.3/24"

    def test_frozen_immutable(self) -> None:
        iface = IPv4Interface.parse("10.0.0.1/24")
        with pytest.raises((AttributeError, TypeError)):
            iface.prefix_length = 16  # type: ignore[misc]


class TestIPv4InterfaceValidation:
    def test_missing_slash_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="format"):
            IPv4Interface.parse("192.168.1.1")

    def test_non_integer_prefix_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="not an integer"):
            IPv4Interface.parse("192.168.1.1/abc")

    def test_prefix_too_large_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            IPv4Interface.parse("192.168.1.1/33")

    def test_malformed_ip_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            IPv4Interface.parse("999.0.0.1/24")

    def test_network_address_rejected(self) -> None:
        # 192.168.1.0 is the network address of /24 — invalid host address.
        with pytest.raises(ConfigurationError, match="not a valid host address"):
            IPv4Interface.parse("192.168.1.0/24")

    def test_broadcast_address_rejected(self) -> None:
        # 192.168.1.255 is the broadcast address of /24 — invalid host address.
        with pytest.raises(ConfigurationError, match="not a valid host address"):
            IPv4Interface.parse("192.168.1.255/24")

    def test_slash0_network_address_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            IPv4Interface.parse("0.0.0.0/0")

    def test_slash32_is_host_address(self) -> None:
        # A /32 has no broadcast concept; the address is always a host address.
        iface = IPv4Interface.parse("192.168.1.1/32")
        assert iface.is_host_address


class TestIPv4InterfaceProperties:
    def test_network(self) -> None:
        iface = IPv4Interface.parse("192.168.1.50/24")
        assert str(iface.network) == "192.168.1.0/24"

    def test_broadcast(self) -> None:
        iface = IPv4Interface.parse("192.168.1.50/24")
        assert str(iface.broadcast) == "192.168.1.255"

    def test_network_address(self) -> None:
        iface = IPv4Interface.parse("10.0.0.5/8")
        assert str(iface.network_address) == "10.0.0.0"

    def test_is_host_address_true(self) -> None:
        iface = IPv4Interface.parse("192.168.1.100/24")
        assert iface.is_host_address

    def test_equality(self) -> None:
        a = IPv4Interface.parse("10.0.0.1/24")
        b = IPv4Interface.parse("10.0.0.1/24")
        assert a == b

    def test_inequality_different_prefix(self) -> None:
        a = IPv4Interface.parse("10.0.0.1/24")
        b = IPv4Interface.parse("10.0.0.1/16")
        assert a != b
