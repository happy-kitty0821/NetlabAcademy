"""
apps.labs.tests.test_cli_view
-----------------------------
The CLI endpoint tells the web terminal when the device is reading the next
line itself (``awaiting_input``) and when that line is a password that must
not be echoed (``input_hidden``).
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User


TOPOLOGY = {
    "nodes": [
        {"id": "sw1", "model": "switch", "hostname": "SW1",
         "catalogId": "cisco-2960", "interfaces": []},
        {"id": "r1", "model": "router", "hostname": "R1",
         "catalogId": "cisco-2911",
         "interfaces": [{"name": "Gi0/0", "ip": "10.0.0.1/24", "shutdown": True}]},
    ],
    "links": [],
}


class CLIViewTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(
            email="student@example.com", password="secret123",
            first_name="Sam", last_name="Student",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        res = self.client.post("/api/v1/labs/simulations/", TOPOLOGY, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.session_id = res.json()["id"]

    def cli(self, device: str, command: str) -> dict:
        res = self.client.post(
            f"/api/v1/labs/simulations/{self.session_id}/cli/",
            {"device_id": device, "command": command, "action": "execute"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_normal_command_does_not_await_input(self):
        body = self.cli("sw1", "enable")
        self.assertEqual(body["prompt"], "SW1#")
        self.assertFalse(body["awaiting_input"])
        self.assertFalse(body["input_hidden"])

    def test_enable_password_prompt_is_hidden(self):
        for cmd in ("enable", "configure terminal", "enable secret class", "end", "disable"):
            self.cli("sw1", cmd)
        body = self.cli("sw1", "enable")
        self.assertEqual(body["prompt"], "Password: ")
        self.assertTrue(body["awaiting_input"])
        self.assertTrue(body["input_hidden"])
        body = self.cli("sw1", "class")
        self.assertEqual(body["prompt"], "SW1#")
        self.assertFalse(body["input_hidden"])

    def test_copy_prompt_awaits_visible_input(self):
        self.cli("sw1", "enable")
        body = self.cli("sw1", "copy running-config startup-config")
        self.assertEqual(body["prompt"], "Destination filename [startup-config]? ")
        self.assertTrue(body["awaiting_input"])
        self.assertFalse(body["input_hidden"])
        body = self.cli("sw1", "")
        self.assertIn("[OK]", body["output"])

    def test_document_shutdown_flag_is_honoured(self):
        self.cli("r1", "enable")
        brief = self.cli("r1", "show ip interface brief")["output"]
        gi00 = next(l for l in brief.splitlines() if l.startswith("Gi0/0 "))
        self.assertIn("administratively down", gi00)
