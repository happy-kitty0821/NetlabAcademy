"""
apps.labs.tests.test_live_links
-------------------------------
Cabling devices in a running lab, the syslog feed, and console messages.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User

TOPOLOGY = {
    "nodes": [
        {"id": "sw1", "model": "switch", "hostname": "SW1", "catalogId": "cisco-2960", "interfaces": []},
        {"id": "sw2", "model": "switch", "hostname": "SW2", "catalogId": "cisco-2960", "interfaces": []},
        {"id": "pc1", "model": "host", "hostname": "PC1", "catalogId": "cisco-pc",
         "interfaces": [{"name": "eth0", "ip": "10.0.0.1/24"}]},
    ],
    "links": [
        {"id": "l1", "device_a": "pc1", "interface_a": "eth0", "device_b": "sw1", "interface_b": "Fa0/1"},
    ],
}


class LiveLinkTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="lab@example.com", password="Str0ng-Lab-Passw0rd!")
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        res = self.client.post("/api/v1/labs/simulations/", TOPOLOGY, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.sid = res.json()["id"]
        self.base = f"/api/v1/labs/simulations/{self.sid}"

    def syslog(self, since=0):
        return self.client.get(f"{self.base}/syslog/?since={since}").json()

    def test_lab_start_logs_connected_ports(self):
        texts = [e["text"] for e in self.syslog()["entries"]]
        self.assertIn("%LINK-3-UPDOWN: Interface FastEthernet0/1, changed state to up", texts)
        self.assertIn("%LINEPROTO-5-UPDOWN: Line protocol on Interface FastEthernet0/1, changed state to up", texts)

    def test_add_link_brings_both_ends_up_and_logs(self):
        start = self.syslog()["last_seq"]
        res = self.client.post(f"{self.base}/links/", {
            "id": "l2", "device_a": "sw1", "interface_a": "Gi0/1",
            "device_b": "sw2", "interface_b": "Gi0/2",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        entries = self.syslog(start)["entries"]
        self.assertEqual(
            sorted((e["hostname"], e["text"]) for e in entries if e["facility"] == "LINK"),
            [("SW1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up"),
             ("SW2", "%LINK-3-UPDOWN: Interface GigabitEthernet0/2, changed state to up")],
        )

    def test_invalid_links_rejected(self):
        for bad in (
            {"device_a": "sw1", "interface_a": "Fa0/1", "device_b": "sw2", "interface_b": "Fa0/1"},  # port in use
            {"device_a": "sw1", "interface_a": "Gi0/9", "device_b": "sw2", "interface_b": "Fa0/1"},  # no such port
            {"device_a": "sw1", "interface_a": "Gi0/1", "device_b": "sw1", "interface_b": "Gi0/2"},  # self link
            {"device_a": "sw1", "interface_a": "Vlan1", "device_b": "sw2", "interface_b": "Fa0/1"},  # not a cable port
        ):
            res = self.client.post(f"{self.base}/links/", {"id": "bad", **bad}, format="json")
            self.assertEqual(res.status_code, 400, bad)

    def test_remove_link_logs_down(self):
        self.client.post(f"{self.base}/links/", {
            "id": "l2", "device_a": "sw1", "interface_a": "Gi0/1",
            "device_b": "sw2", "interface_b": "Gi0/1",
        }, format="json")
        start = self.syslog()["last_seq"]
        self.assertEqual(self.client.delete(f"{self.base}/links/l2/").status_code, 204)
        texts = [e["text"] for e in self.syslog(start)["entries"]]
        self.assertIn("%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down", texts)
        self.assertEqual(self.client.delete(f"{self.base}/links/l2/").status_code, 404)

    def test_console_receives_device_messages(self):
        # First read shows the boot messages for SW1 only.
        first = self.client.get(f"{self.base}/console/sw1/").json()["console"]
        self.assertTrue(any("FastEthernet0/1, changed state to up" in m for m in first))
        self.assertEqual(self.client.get(f"{self.base}/console/sw1/").json()["console"], [])
        # A cable plugged in elsewhere shows up on SW2's console.
        self.client.get(f"{self.base}/console/sw2/")
        self.client.post(f"{self.base}/links/", {
            "id": "l2", "device_a": "sw1", "interface_a": "Gi0/1",
            "device_b": "sw2", "interface_b": "Gi0/1",
        }, format="json")
        sw2 = self.client.get(f"{self.base}/console/sw2/").json()["console"]
        self.assertIn("%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up", sw2)

    def test_cli_response_carries_console_messages(self):
        cli = f"{self.base}/cli/"
        for cmd in ("enable", "configure terminal", "interface fa0/1", "shutdown"):
            self.client.post(cli, {"device_id": "sw1", "command": cmd}, format="json")
        body = self.client.post(cli, {"device_id": "sw1", "command": "end"}, format="json").json()
        self.assertIn("%SYS-5-CONFIG_I: Configured from console by console", body["console"])

    def test_wipe_keeps_live_links(self):
        self.client.post(f"{self.base}/links/", {
            "id": "l2", "device_a": "sw1", "interface_a": "Gi0/1",
            "device_b": "sw2", "interface_b": "Gi0/1",
        }, format="json")
        self.client.post(f"{self.base}/reset/")
        texts = [e["text"] for e in self.syslog()["entries"]]
        self.assertIn("%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to up", texts)
