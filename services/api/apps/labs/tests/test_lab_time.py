"""
apps.labs.tests.test_lab_time
-----------------------------
A running lab's time follows the wall clock, so switch timers (errdisable
recovery, MAC aging) fire between requests.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.labs.services import simulation_adapter as adapter

TOPOLOGY = {
    "nodes": [
        {"id": "sw1", "model": "switch", "hostname": "SW1", "catalogId": "cisco-2960", "interfaces": []},
        {"id": "sw2", "model": "switch", "hostname": "SW2", "catalogId": "cisco-2960", "interfaces": []},
    ],
    "links": [
        {"id": "l1", "device_a": "sw1", "interface_a": "Fa0/24", "device_b": "sw2", "interface_b": "Fa0/24"},
    ],
}


class LabTimeTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="time@example.com", password="Str0ng-Lab-Passw0rd!")
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        res = self.client.post("/api/v1/labs/simulations/", TOPOLOGY, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.sid = res.json()["id"]
        self.base = f"/api/v1/labs/simulations/{self.sid}"

    def console(self, command):
        res = self.client.post(f"{self.base}/cli/",
                               {"device_id": "sw1", "command": command, "action": "execute"},
                               format="json")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def let_time_pass(self, seconds):
        """Pretend *seconds* of wall-clock time went by since the last request."""
        adapter._sessions[self.sid].last_wall -= seconds

    def test_lab_time_follows_the_wall_clock(self):
        sim = adapter._sessions[self.sid].simulation
        before = sim.lab_time
        self.let_time_pass(42)
        self.client.get(f"{self.base}/syslog/")
        self.assertGreaterEqual(sim.lab_time - before, 42)

    def test_errdisable_recovery_fires_between_requests(self):
        for cmd in ("enable", "configure terminal",
                    "errdisable recovery cause bpduguard", "errdisable recovery interval 30",
                    "interface Fa0/24", "spanning-tree bpduguard enable", "end"):
            self.console(cmd)
        sim = adapter._sessions[self.sid].simulation
        port = sim.topology.devices["sw1"].interfaces["Fa0/24"]
        self.assertEqual(port.err_disabled, "bpduguard")
        self.let_time_pass(31)
        texts = [e["text"] for e in self.client.get(f"{self.base}/syslog/").json()["entries"]]
        self.assertIn("%PM-4-ERR_RECOVER: Attempting to recover from bpduguard err-disable "
                      "state on Fa0/24", texts)
