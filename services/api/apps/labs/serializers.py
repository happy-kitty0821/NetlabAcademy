"""
apps.labs.serializers
~~~~~~~~~~~~~~~~~~~~~
DRF serializers for the labs / simulation API.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import Lab


class InterfaceSpecSerializer(serializers.Serializer):
    """One interface on a device in the topology document."""
    name = serializers.CharField(max_length=64)
    mac_seed = serializers.IntegerField(required=False)
    ip = serializers.CharField(required=False, allow_blank=True)
    gateway = serializers.CharField(required=False, allow_blank=True)


class NodeSpecSerializer(serializers.Serializer):
    """One node (device) in the topology document."""
    id = serializers.CharField(max_length=64)
    model = serializers.ChoiceField(choices=["host", "switch", "router"])
    hostname = serializers.CharField(max_length=128, required=False)
    catalogId = serializers.CharField(max_length=64, required=False, allow_blank=True)
    interfaces = InterfaceSpecSerializer(many=True)


class LinkSpecSerializer(serializers.Serializer):
    """One link between two device interfaces."""
    id = serializers.CharField(max_length=64)
    device_a = serializers.CharField(max_length=64)
    interface_a = serializers.CharField(max_length=64)
    device_b = serializers.CharField(max_length=64)
    interface_b = serializers.CharField(max_length=64)


class TopologyDocumentSerializer(serializers.Serializer):
    """The full topology document submitted to create a simulation session."""
    nodes = NodeSpecSerializer(many=True, min_length=1)
    links = LinkSpecSerializer(many=True, required=False, default=list)


class PingRequestSerializer(serializers.Serializer):
    """Request body for issuing a ping from a device."""
    device_id = serializers.CharField(max_length=64)
    target_ip = serializers.CharField(max_length=45)
    count = serializers.IntegerField(min_value=1, max_value=100, default=4)


# ── Lab persistence ────────────────────────────────────────────────────────────


class LabSerializer(serializers.ModelSerializer):
    """Full representation of a Lab, including the topology canvas.

    ``owner_name`` is read-only and sourced from the owner's ``full_name``
    property so the frontend can attribute a lab without a second request.
    The ``topology`` field stores the raw React Flow canvas document shaped
    as ``{"nodes": [...], "edges": [...]}``.
    """

    owner_name = serializers.CharField(source="owner.full_name", read_only=True)

    class Meta:
        model = Lab
        fields = [
            "id",
            "name",
            "description",
            "topology",
            "created_at",
            "updated_at",
            "owner_name",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "owner_name"]


class LabListSerializer(serializers.ModelSerializer):
    """Compact lab list item: omit the topology payload, add counts.

    List responses return a plain array (the view sets
    ``pagination_class=None``), so this serializer keeps each entry small by
    excluding ``topology`` and ``owner_name`` and exposing derived device and
    link counts pulled from the canvas document.
    """

    device_count = serializers.SerializerMethodField()
    link_count = serializers.SerializerMethodField()

    class Meta:
        model = Lab
        fields = [
            "id",
            "name",
            "description",
            "created_at",
            "updated_at",
            "device_count",
            "link_count",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "device_count",
            "link_count",
        ]

    def _topology_dict(self, obj: Lab) -> dict:
        """Return the topology as a dict, tolerating a non-dict (e.g. list).

        ``JSONField(default=dict)`` normally yields a dict, but legacy or
        malformed rows could store another JSON type; guard those cases so a
        broken row never raises in the list view.
        """
        topology = obj.topology
        return topology if isinstance(topology, dict) else {}

    def get_device_count(self, obj: Lab) -> int:
        nodes = self._topology_dict(obj).get("nodes", [])
        return len(nodes) if isinstance(nodes, list) else 0

    def get_link_count(self, obj: Lab) -> int:
        edges = self._topology_dict(obj).get("edges", [])
        return len(edges) if isinstance(edges, list) else 0
