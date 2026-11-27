"""
apps.labs.tests.test_simulation_adapter_catalog
------------------------------------------------
Tests for the INTERFACE_CATALOG integration in build_topology_from_document.

These tests run via `python manage.py test apps.labs` and also via pytest
when the Django service is on the path.  They import directly from the
adapter module; no HTTP layer is involved.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.labs.services.simulation_adapter import build_topology_from_document


class TestCisco2960Catalog(SimpleTestCase):
    """
    catalog_id 'cisco-2960' must match the real Catalyst 2960-24TT:
    FastEthernet0/1-0/24 plus GigabitEthernet0/1-0/2 uplinks.
    """

    def _doc(self, **kwargs):
        node = {
            "id": "sw1",
            "model": "switch",
            "catalogId": "cisco-2960",
            "interfaces": [],
        }
        node.update(kwargs)
        return {"nodes": [node], "links": []}

    def test_cisco2960_generates_24_fastethernet_and_2_gigabit_ports(self):
        topo = build_topology_from_document(self._doc())
        names = [n for n in topo.devices["sw1"].interfaces if not n.startswith("Vlan")]
        self.assertEqual(len(names), 26, names)
        self.assertEqual(sum(n.startswith("Fa0/") for n in names), 24)
        self.assertEqual(sum(n.startswith("Gi0/") for n in names), 2)

    def test_cisco2960_fastethernet_speed_and_cost(self):
        topo = build_topology_from_document(self._doc())
        for name, iface in topo.devices["sw1"].interfaces.items():
            if name.startswith("Fa0/"):
                self.assertEqual(iface.speed_kbps, 100_000, name)
                self.assertEqual(iface.stp_path_cost, 19, name)

    def test_cisco2960_uplink_speed_and_cost(self):
        topo = build_topology_from_document(self._doc())
        for name in ("Gi0/1", "Gi0/2"):
            iface = topo.devices["sw1"].interfaces[name]
            self.assertEqual(iface.speed_kbps, 1_000_000, name)
            self.assertEqual(iface.stp_path_cost, 4, name)

    def test_cisco2960_port_names_match_hardware(self):
        topo = build_topology_from_document(self._doc())
        expected = {f"Fa0/{i}" for i in range(1, 25)} | {"Gi0/1", "Gi0/2", "Vlan1"}
        self.assertEqual(set(topo.devices["sw1"].interfaces), expected)
        self.assertNotIn("Fa0/0", topo.devices["sw1"].interfaces)

    def test_cisco2960_ships_vlan1_svi_shut_down(self):
        from simulator_core.types import InterfaceState
        vlan1 = build_topology_from_document(self._doc()).devices["sw1"].interfaces["Vlan1"]
        self.assertEqual(vlan1.admin_state, InterfaceState.DOWN)
        self.assertIsNone(vlan1.ip_config)

    def test_cisco2960_supports_management_svi_but_not_routing(self):
        topo = build_topology_from_document(self._doc())
        self.assertTrue(topo.devices["sw1"].supports_svi)
        self.assertFalse(topo.devices["sw1"].supports_l3_routing)

    def test_cisco2960_ip_preserved_on_first_interface(self):
        """
        When the JSON interface list has an IP on its first entry, it must be
        applied to Fa0/1, the first port of the generated catalog interfaces.
        """
        doc = {
            "nodes": [
                {
                    "id": "sw1",
                    "model": "switch",
                    "catalogId": "cisco-2960",
                    "interfaces": [{"name": "eth0", "ip": "10.0.0.1/24"}],
                }
            ],
            "links": [],
        }
        topo = build_topology_from_document(doc)
        device = topo.devices["sw1"]
        fa0_1 = device.interfaces.get("Fa0/1")
        self.assertIsNotNone(fa0_1, "Fa0/1 must exist in the generated interfaces")
        self.assertIsNotNone(
            fa0_1.ip_config,
            "Fa0/1 must have ip_config set from the original interface list",
        )
        self.assertEqual(str(fa0_1.ip_config), "10.0.0.1/24")

    def test_cisco2960_mac_seeds_are_deterministic(self):
        """Same document must produce the same MAC addresses (determinism).

        Unlike Python's built-in hash(), hashlib.md5 is not randomised by
        PYTHONHASHSEED. We verify (a) two calls in the same process agree,
        and (b) the seed for a known input matches the expected MD5-derived
        value, confirming cross-process stability.
        """
        import hashlib
        doc = self._doc()
        topo1 = build_topology_from_document(doc)
        topo2 = build_topology_from_document(doc)
        macs1 = {n: i.mac.value for n, i in topo1.devices["sw1"].interfaces.items()}
        macs2 = {n: i.mac.value for n, i in topo2.devices["sw1"].interfaces.items()}
        self.assertEqual(macs1, macs2, "MAC addresses must be deterministic")

        # Verify the seed for Fa0/1 equals the expected MD5-derived constant.
        # If this assertion ever fails it means the hash function changed.
        expected_seed = int(hashlib.md5(
            ("sw1" + "Fa0/1").encode()
        ).hexdigest(), 16) % (2 ** 31)
        # Recompute from the actual topo to confirm the formula was applied.
        # We cannot easily extract the seed after MAC generation, but we can
        # confirm reproducibility by checking the two topologies agree AND
        # that the seed formula is the MD5 one (not hash()).
        import random as _random
        from simulator_core.addresses import MACAddress
        mac_from_expected_seed = MACAddress.generate(_random.Random(expected_seed))
        self.assertEqual(
            topo1.devices["sw1"].interfaces["Fa0/1"].mac,
            mac_from_expected_seed,
            "MAC seed must come from hashlib.md5 (cross-process stable), not hash()",
        )


class TestUnknownCatalogIdFallback(SimpleTestCase):
    """An unknown catalogId must fall back to JSON-supplied interfaces."""

    def test_unknown_catalog_id_falls_back_to_json(self):
        doc = {
            "nodes": [
                {
                    "id": "sw1",
                    "model": "switch",
                    "catalogId": "custom-device",
                    "interfaces": [
                        {"name": "eth0", "mac_seed": 1},
                        {"name": "eth1", "mac_seed": 2},
                    ],
                }
            ],
            "links": [],
        }
        topo = build_topology_from_document(doc)
        device = topo.devices["sw1"]
        self.assertEqual(len(device.interfaces), 2)
        self.assertIn("eth0", device.interfaces)
        self.assertIn("eth1", device.interfaces)

    def test_unknown_catalog_id_uses_json_names_exactly(self):
        doc = {
            "nodes": [
                {
                    "id": "sw1",
                    "model": "switch",
                    "catalogId": "my-custom-switch-99",
                    "interfaces": [
                        {"name": "FastEthernet0/1"},
                        {"name": "FastEthernet0/2"},
                    ],
                }
            ],
            "links": [],
        }
        topo = build_topology_from_document(doc)
        device = topo.devices["sw1"]
        self.assertIn("FastEthernet0/1", device.interfaces)
        self.assertIn("FastEthernet0/2", device.interfaces)


class TestNoCatalogIdFallback(SimpleTestCase):
    """When catalogId is absent, JSON-supplied interfaces are used unchanged."""

    def test_no_catalog_id_uses_json_interfaces(self):
        doc = {
            "nodes": [
                {
                    "id": "sw1",
                    "model": "switch",
                    "interfaces": [
                        {"name": "Gi0/0", "mac_seed": 10},
                        {"name": "Gi0/1", "mac_seed": 11},
                        {"name": "Gi0/2", "mac_seed": 12},
                    ],
                }
            ],
            "links": [],
        }
        topo = build_topology_from_document(doc)
        device = topo.devices["sw1"]
        self.assertEqual(len(device.interfaces), 3)
        for name in ("Gi0/0", "Gi0/1", "Gi0/2"):
            self.assertIn(name, device.interfaces)

    def test_no_catalog_id_host_uses_json_interfaces(self):
        doc = {
            "nodes": [
                {
                    "id": "pc1",
                    "model": "host",
                    "interfaces": [
                        {"name": "eth0", "mac_seed": 5, "ip": "192.168.1.1/24"},
                    ],
                }
            ],
            "links": [],
        }
        topo = build_topology_from_document(doc)
        device = topo.devices["pc1"]
        self.assertIn("eth0", device.interfaces)
        self.assertIsNotNone(device.interfaces["eth0"].ip_config)


class TestCisco2911Catalog(SimpleTestCase):
    """catalog_id 'cisco-2911' must generate exactly 3 GigabitEthernet ports."""

    def test_cisco2911_generates_3_gigabitethernet_ports(self):
        doc = {
            "nodes": [
                {
                    "id": "r1",
                    "model": "router",
                    "catalogId": "cisco-2911",
                    "interfaces": [],
                }
            ],
            "links": [],
        }
        topo = build_topology_from_document(doc)
        device = topo.devices["r1"]
        self.assertEqual(len(device.interfaces), 3)
        for name in device.interfaces:
            self.assertTrue(
                name.startswith("Gi0/"),
                f"Interface {name!r} does not start with 'Gi0/'",
            )

    def test_cisco2911_speed_is_1_000_000_kbps(self):
        doc = {
            "nodes": [
                {
                    "id": "r1",
                    "model": "router",
                    "catalogId": "cisco-2911",
                    "interfaces": [],
                }
            ],
            "links": [],
        }
        topo = build_topology_from_document(doc)
        for iface in topo.devices["r1"].interfaces.values():
            self.assertEqual(iface.speed_kbps, 1_000_000)


class TestEndpointCatalogDevices(SimpleTestCase):
    """cisco-pc, cisco-laptop, cisco-server all generate one eth0 port."""

    def _doc_for(self, catalog_id: str, model: str = "host"):
        return {
            "nodes": [
                {
                    "id": "dev1",
                    "model": model,
                    "catalogId": catalog_id,
                    "interfaces": [],
                }
            ],
            "links": [],
        }

    def test_cisco_pc_generates_one_eth0(self):
        topo = build_topology_from_document(self._doc_for("cisco-pc"))
        device = topo.devices["dev1"]
        self.assertEqual(len(device.interfaces), 1)
        self.assertIn("eth0", device.interfaces)

    def test_cisco_laptop_generates_one_eth0(self):
        topo = build_topology_from_document(self._doc_for("cisco-laptop"))
        device = topo.devices["dev1"]
        self.assertEqual(len(device.interfaces), 1)
        self.assertIn("eth0", device.interfaces)

    def test_cisco_server_generates_one_eth0(self):
        topo = build_topology_from_document(self._doc_for("cisco-server"))
        device = topo.devices["dev1"]
        self.assertEqual(len(device.interfaces), 1)
        self.assertIn("eth0", device.interfaces)


class TestRouterDefaultShutdown(SimpleTestCase):
    """IOS router interfaces ship administratively down."""

    def _router(self, interfaces):
        return build_topology_from_document({
            "nodes": [{"id": "r1", "model": "router", "catalogId": "cisco-2911",
                       "interfaces": interfaces}],
            "links": [],
        }).devices["r1"]

    def test_unconfigured_router_ports_start_shutdown(self):
        from simulator_core.types import InterfaceState
        r1 = self._router([])
        for name, iface in r1.interfaces.items():
            self.assertEqual(iface.admin_state, InterfaceState.DOWN, name)

    def test_router_port_addressed_in_document_starts_enabled(self):
        from simulator_core.types import InterfaceState
        r1 = self._router([{"name": "Gi0/0", "ip": "10.0.0.1/24"}])
        self.assertEqual(r1.interfaces["Gi0/0"].admin_state, InterfaceState.UP)
        self.assertEqual(r1.interfaces["Gi0/1"].admin_state, InterfaceState.DOWN)

    def test_switch_ports_start_enabled(self):
        from simulator_core.types import InterfaceState
        topo = build_topology_from_document({
            "nodes": [{"id": "sw1", "model": "switch", "catalogId": "cisco-2960",
                       "interfaces": []}],
            "links": [],
        })
        for name, iface in topo.devices["sw1"].interfaces.items():
            if name.startswith("Vlan"):
                continue  # the management SVI ships shut down (tested above)
            self.assertEqual(iface.admin_state, InterfaceState.UP, name)
