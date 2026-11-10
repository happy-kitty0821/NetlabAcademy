"""
simulator_core.topology
~~~~~~~~~~~~~~~~~~~~~~~
Topology domain objects: Interface, Device, Link, Topology.

These objects represent *configuration* — the static or configurable
description of a network.  Runtime protocol state (ARP cache, MAC table,
etc.) lives in the device protocol objects in simulator_core.devices.

All mutation happens through explicit setters; no untyped dict is used as the
canonical representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from simulator_core.addresses import IPv4Interface, MACAddress
from simulator_core.exceptions import ConfigurationError, TopologyError
from simulator_core.types import DeviceModel, InterfaceState
from simulator_core.device_config import DeviceConfig

# ---------------------------------------------------------------------------
# Topology size limits (configurable defaults)
# ---------------------------------------------------------------------------

MAX_NODES: int = 64
MAX_LINKS: int = 128


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


@dataclass
class Interface:
    """
    One physical or logical port on a device.

    Attributes
    ----------
    name:
        Human-readable name unique within the owning device, e.g. ``"eth0"``.
    mac:
        The 48-bit unicast MAC address assigned to this interface.
    admin_state:
        Whether the interface has been administratively enabled or disabled.
    oper_state:
        Current operational state (derived from admin_state and link state).
        Kept in sync by the simulation engine.
    ip_config:
        Optional IPv4 address and prefix.  ``None`` means unconfigured.
    default_gateway:
        Optional IPv4 gateway address.  Used by Host for route lookups.
    rx_frames:
        Count of frames received (incremented by the simulation engine).
    tx_frames:
        Count of frames transmitted (incremented by the simulation engine).
    """

    name: str
    mac: MACAddress
    admin_state: InterfaceState = InterfaceState.UP
    oper_state: InterfaceState = InterfaceState.UP
    ip_config: Optional[IPv4Interface] = None
    default_gateway: Optional[str] = None  # dotted-decimal IPv4 string

    # ── Port media type & speed ───────────────────────────────────────────────
    # "ethernet" (10 Mbps), "fastethernet" (100 Mbps), "gigabitethernet" (1 Gbps),
    # "tengigabitethernet" (10 Gbps), "loopback" (virtual, no speed)
    port_type: str = "gigabitethernet"
    # Configured speed in Kbps (auto-detected from port_type, overridable).
    # None means auto (use port_type default).
    speed_kbps: Optional[int] = None
    # Duplex mode: "auto" | "full" | "half"
    duplex: str = "auto"

    # ── Switchport configuration ──────────────────────────────────────────────
    # Port mode: "access" | "trunk" | "dynamic_auto" | "dynamic_desirable" | "routed"
    switchport_mode: str = "access"
    # Access VLAN (used when mode == "access")
    vlan: int = 1
    # Trunk configuration (used when mode == "trunk")
    trunk_native_vlan: int = 1
    trunk_allowed_vlans: Optional[list] = None   # None = all; list of ints
    trunk_encapsulation: str = "dot1q"           # "dot1q" | "isl" (ISL not simulated)

    # ── STP per-interface settings ────────────────────────────────────────────
    stp_portfast: bool = False
    stp_bpduguard: bool = False
    stp_bpdufilter: bool = False
    stp_guard: str = "none"          # "none" | "root" | "loop"
    stp_port_priority: int = 128     # 0-240, increment of 16
    stp_path_cost: Optional[int] = None   # None = auto-calculated from speed

    # ── Counters ──────────────────────────────────────────────────────────────
    rx_frames: int = field(default=0, repr=False)
    tx_frames: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        # Auto-detect port type from name if not explicitly set
        if not hasattr(self, '_port_type_detected'):
            from simulator_core.port_types import detect_port_type, PortType
            self._port_type_detected = detect_port_type(self.name)
            # Set port_type string from detected type if it's still default
            if self.port_type == "gigabitethernet":
                self.port_type = self._port_type_detected.value
            # Auto-set speed from port type if not explicitly configured
            if self.speed_kbps is None:
                self.speed_kbps = self._port_type_detected.speed_kbps

    def set_ip(self, cidr: str) -> None:
        """
        Assign an IPv4 address and prefix to this interface.

        Parameters
        ----------
        cidr:
            A CIDR string such as ``"192.168.1.1/24"``.

        Raises
        ------
        ConfigurationError
            If the CIDR string is malformed or the address is not a valid
            host address.
        """
        self.ip_config = IPv4Interface.parse(cidr)

    def set_gateway(self, gateway_ip: str) -> None:
        """
        Set the default gateway for this interface.

        Parameters
        ----------
        gateway_ip:
            A dotted-decimal IPv4 address string, e.g. ``"192.168.1.254"``.

        Raises
        ------
        ConfigurationError
            If the string is not a valid IPv4 address.
        """
        from ipaddress import IPv4Address  # stdlib — no host I/O

        try:
            IPv4Address(gateway_ip)
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid gateway address {gateway_ip!r}: {exc}"
            ) from exc
        self.default_gateway = gateway_ip


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------


@dataclass
class Device:
    """
    A simulated network device.

    Attributes
    ----------
    id:
        Stable UUID string.  Must be unique within a Topology.
    model:
        Determines which protocol logic is instantiated for this device.
    hostname:
        Human-readable label.
    interfaces:
        Ordered mapping of interface name → Interface.
    config:
        Shared device configuration (users, lines, logging, enable secret).
    """

    id: str
    model: DeviceModel
    hostname: str
    interfaces: dict[str, Interface] = field(default_factory=dict)
    config: DeviceConfig = field(default_factory=DeviceConfig)

    def add_interface(self, interface: Interface) -> None:
        """
        Add an interface to this device.

        Raises
        ------
        TopologyError
            If an interface with the same name already exists on this device.
        """
        if interface.name in self.interfaces:
            raise TopologyError(
                f"Device {self.hostname!r} has a duplicate interface name "
                f"{interface.name!r}: an interface with that name already exists."
            )
        self.interfaces[interface.name] = interface

    def get_interface(self, name: str) -> Interface:
        """
        Return the named interface.

        Raises
        ------
        TopologyError
            If no interface with that name exists.
        """
        try:
            return self.interfaces[name]
        except KeyError:
            raise TopologyError(
                f"Device {self.hostname!r} has no interface named {name!r}."
            )


# ---------------------------------------------------------------------------
# Link
# ---------------------------------------------------------------------------


@dataclass
class Link:
    """
    A point-to-point Ethernet link between two device interfaces.

    Attributes
    ----------
    id:
        Stable UUID string.  Must be unique within a Topology.
    endpoint_a, endpoint_b:
        Each endpoint is a ``(device_id, interface_name)`` tuple.
    admin_state:
        Whether the link is administratively up.  When DOWN, any frame
        traversal produces a FrameDropped event.
    """

    id: str
    endpoint_a: tuple[str, str]  # (device_id, interface_name)
    endpoint_b: tuple[str, str]
    admin_state: InterfaceState = InterfaceState.UP


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------


@dataclass
class Topology:
    """
    A complete network topology: a set of devices and links.

    The topology is the *configuration description* of the network.  It does
    not contain runtime protocol state.

    Attributes
    ----------
    devices:
        Mapping of device_id → Device.
    links:
        List of all links in the topology.
    max_nodes:
        Maximum number of devices allowed.
    max_links:
        Maximum number of links allowed.
    """

    devices: dict[str, Device] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)
    max_nodes: int = MAX_NODES
    max_links: int = MAX_LINKS

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_device(self, device: Device) -> None:
        """
        Add a device to the topology.

        Raises
        ------
        TopologyError
            If a device with the same ID already exists, or the node cap
            would be exceeded.
        """
        if device.id in self.devices:
            raise TopologyError(
                f"Topology already contains a device with id {device.id!r}."
            )
        if len(self.devices) >= self.max_nodes:
            raise TopologyError(
                f"Topology node limit ({self.max_nodes}) reached; cannot add "
                f"device {device.hostname!r}."
            )
        self.devices[device.id] = device

    def add_link(self, link: Link) -> None:
        """
        Add a link to the topology.

        Raises
        ------
        TopologyError
            If the link cap would be exceeded.  Full structural validation is
            deferred to :meth:`validate`.
        """
        if len(self.links) >= self.max_links:
            raise TopologyError(
                f"Topology link limit ({self.max_links}) reached; cannot add "
                f"link {link.id!r}."
            )
        self.links.append(link)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Perform a full structural validation pass.

        Raises
        ------
        TopologyError
            On any violation:
            - Fewer than 1 device.
            - Node or link cap exceeded.
            - Duplicate device IDs (already prevented by add_device).
            - Duplicate interface names within a device.
            - A link whose endpoint references a missing device or interface.
            - A self-link (both endpoints on the same device).
            - An interface appearing in more than one link.
        """
        if not self.devices:
            raise TopologyError("Topology must contain at least one device.")

        if len(self.devices) > self.max_nodes:
            raise TopologyError(
                f"Topology has {len(self.devices)} nodes which exceeds the "
                f"maximum of {self.max_nodes}."
            )

        if len(self.links) > self.max_links:
            raise TopologyError(
                f"Topology has {len(self.links)} links which exceeds the "
                f"maximum of {self.max_links}."
            )

        # Check for duplicate interface names within each device.
        for device in self.devices.values():
            seen: set[str] = set()
            for iface_name in device.interfaces:
                if iface_name in seen:
                    raise TopologyError(
                        f"Device {device.hostname!r} has duplicate interface "
                        f"name {iface_name!r}."
                    )
                seen.add(iface_name)

        # Check link endpoints and build endpoint usage map.
        endpoint_usage: dict[tuple[str, str], str] = {}  # (dev_id, iface) → link_id

        for link in self.links:
            for endpoint in (link.endpoint_a, link.endpoint_b):
                dev_id, iface_name = endpoint

                # Device must exist.
                if dev_id not in self.devices:
                    raise TopologyError(
                        f"Link {link.id!r} references non-existent device "
                        f"{dev_id!r}."
                    )

                # Interface must exist on that device.
                device = self.devices[dev_id]
                if iface_name not in device.interfaces:
                    raise TopologyError(
                        f"Link {link.id!r} references non-existent interface "
                        f"{iface_name!r} on device {device.hostname!r}."
                    )

                # Interface must not already be in another link.
                if endpoint in endpoint_usage:
                    raise TopologyError(
                        f"Interface {iface_name!r} on device "
                        f"{device.hostname!r} appears in more than one link "
                        f"({endpoint_usage[endpoint]!r} and {link.id!r})."
                    )
                endpoint_usage[endpoint] = link.id

            # Self-link check.
            if link.endpoint_a[0] == link.endpoint_b[0]:
                dev_id = link.endpoint_a[0]
                hostname = self.devices[dev_id].hostname
                raise TopologyError(
                    f"Link {link.id!r} is a self-link: both endpoints are on "
                    f"device {hostname!r} ({dev_id!r})."
                )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def neighbours(
        self,
        device_id: str,
        interface_name: str,
    ) -> Optional[tuple[str, str]]:
        """
        Return ``(peer_device_id, peer_interface_name)`` for the device/interface
        pair, or ``None`` if no link connects to that interface.
        """
        target = (device_id, interface_name)
        for link in self.links:
            if link.endpoint_a == target:
                return link.endpoint_b
            if link.endpoint_b == target:
                return link.endpoint_a
        return None

    def get_link(
        self,
        device_id: str,
        interface_name: str,
    ) -> Optional[Link]:
        """
        Return the Link object connected to ``(device_id, interface_name)``,
        or ``None`` if unconnected.
        """
        target = (device_id, interface_name)
        for link in self.links:
            if link.endpoint_a == target or link.endpoint_b == target:
                return link
        return None
