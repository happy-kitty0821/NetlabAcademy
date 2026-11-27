"""
apps.labs.models
~~~~~~~~~~~~~~~~~
Domain models for the labs app.

``Lab`` is the persisted snapshot of a user's React Flow workspace canvas.
The ``topology`` field stores the raw canvas document — ``{nodes, edges}`` —
exactly as drawn by the user (positions included). It is intentionally not
the lossy simulator ``TopologyDocument`` produced by
``convertFlowToTopology``: persistence keeps the full canvas so opening a
saved lab restores the editor pixel-for-pixel, and a simulation session is
reconstructed from the canvas at run time.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Lab(models.Model):
    """
    A single user's saved lab.

    Labs are private to their owner: every view filters the queryset by
    ``request.user``, so no user can read or mutate another user's lab.

    The ``topology`` JSON field holds the React Flow canvas document shaped
    as ``{"nodes": [...], "edges": [...]}`` (see the frontend ``convertFlowToTopology``
    helper for the relationship to the simulator topology document).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="labs",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    # React Flow canvas document: {"nodes": [...], "edges": [...]}
    topology = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name
