"""
apps.labs.tests.test_lab_crud
-----------------------------
Authorization and CRUD tests for the Lab persistence API.

The lab endpoints are owner-scoped: every view filters its queryset by
``request.user``, so a user can never read or mutate another user's lab.
These tests run via ``python -m pytest apps/labs/tests/`` (pytest-django)
and also via ``python manage.py test apps.labs``.
"""

from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.labs.models import Lab

LIST_URL = "/api/v1/labs/labs/"


def detail_url(lab_id) -> str:
    return f"/api/v1/labs/labs/{lab_id}/"


def make_topology():
    """A small React Flow canvas document: two nodes, one edge."""
    return {
        "nodes": [
            {"id": "sw1", "type": "switch"},
            {"id": "sw2", "type": "switch"},
        ],
        "edges": [
            {"id": "e1", "source": "sw1", "target": "sw2"},
        ],
    }


class LabCRUDTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="secret123",
            first_name="Ada",
            last_name="Lovelace",
        )
        self.other = User.objects.create_user(
            email="other@example.com",
            password="secret123",
            first_name="Grace",
            last_name="Hopper",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    # ── Create ────────────────────────────────────────────────────────

    def test_create_returns_201_and_owns_lab(self):
        topology = make_topology()
        response = self.client.post(
            LIST_URL,
            {
                "name": "My Lab",
                "description": "Two switches and a link",
                "topology": topology,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.data
        self.assertEqual(data["name"], "My Lab")
        self.assertEqual(data["description"], "Two switches and a link")
        self.assertEqual(data["topology"], topology)
        # owner_name is read-only and sourced from the owner's full_name
        self.assertEqual(data["owner_name"], "Ada Lovelace")
        # read-only fields are returned
        for field in ("id", "created_at", "updated_at"):
            self.assertIn(field, data)
        # the lab is actually owned by the caller
        lab = Lab.objects.get(id=data["id"])
        self.assertEqual(lab.owner, self.owner)

    def test_create_without_topology_defaults_to_empty(self):
        response = self.client.post(
            LIST_URL,
            {"name": "Empty Lab"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["topology"], {})

    # ── List ──────────────────────────────────────────────────────────

    def test_list_returns_only_callers_labs(self):
        Lab.objects.create(
            owner=self.owner,
            name="owner-lab",
            topology={"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": [{"id": "e1"}]},
        )
        Lab.objects.create(
            owner=self.other,
            name="other-lab",
            topology={"nodes": [{"id": "n9"}], "edges": []},
        )
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        # plain array — no pagination envelope
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 1)
        item = response.data[0]
        self.assertEqual(item["name"], "owner-lab")
        # list items expose derived counts
        self.assertEqual(item["device_count"], 2)
        self.assertEqual(item["link_count"], 1)
        # list items omit the heavy payload and owner_name
        self.assertNotIn("topology", item)
        self.assertNotIn("owner_name", item)

    def test_list_is_ordered_by_updated_at_desc(self):
        import time

        first = Lab.objects.create(owner=self.owner, name="first", topology={})
        # bump updated_at on a second lab so it sorts first
        second = Lab.objects.create(owner=self.owner, name="second", topology={})
        first.name = "first-renamed"
        first.save()
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.data]
        # the most-recently-updated lab comes first
        self.assertEqual(names[0], "first-renamed")

    # ── Retrieve ──────────────────────────────────────────────────────

    def test_retrieve_returns_topology_and_owner_name(self):
        topology = make_topology()
        lab = Lab.objects.create(owner=self.owner, name="Retrieve Me", topology=topology)
        response = self.client.get(detail_url(lab.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(lab.id))
        self.assertEqual(response.data["name"], "Retrieve Me")
        self.assertEqual(response.data["topology"], topology)
        self.assertEqual(response.data["owner_name"], "Ada Lovelace")

    # ── Update ───────────────────────────────────────────────────────

    def test_patch_updates_name_and_topology(self):
        lab = Lab.objects.create(owner=self.owner, name="Before", topology={"nodes": [], "edges": []})
        new_topology = make_topology()
        response = self.client.patch(
            detail_url(lab.id),
            {"name": "After", "topology": new_topology},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "After")
        self.assertEqual(response.data["topology"], new_topology)
        lab.refresh_from_db()
        self.assertEqual(lab.name, "After")
        self.assertEqual(lab.topology, new_topology)

    # ── Delete ───────────────────────────────────────────────────────

    def test_delete_returns_204_and_removes_lab(self):
        lab = Lab.objects.create(owner=self.owner, name="Delete Me", topology={})
        response = self.client.delete(detail_url(lab.id))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Lab.objects.filter(id=lab.id).exists())

    # ── Authorization ─────────────────────────────────────────────────

    def test_unauthenticated_returns_401(self):
        anon = APIClient()  # not authenticated
        response = anon.get(LIST_URL)
        self.assertEqual(response.status_code, 401)

    def test_non_owner_retrieve_returns_404(self):
        lab = Lab.objects.create(owner=self.other, name="Secret", topology={})
        response = self.client.get(detail_url(lab.id))
        self.assertEqual(response.status_code, 404)

    def test_non_owner_patch_returns_404(self):
        lab = Lab.objects.create(owner=self.other, name="Secret", topology={})
        response = self.client.patch(
            detail_url(lab.id),
            {"name": "Hijacked"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        # the lab is untouched
        lab.refresh_from_db()
        self.assertEqual(lab.name, "Secret")

    def test_non_owner_delete_returns_404(self):
        lab = Lab.objects.create(owner=self.other, name="Secret", topology={})
        response = self.client.delete(detail_url(lab.id))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Lab.objects.filter(id=lab.id).exists())

    def test_non_owner_does_not_appear_in_list(self):
        Lab.objects.create(owner=self.other, name="Secret", topology={})
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
