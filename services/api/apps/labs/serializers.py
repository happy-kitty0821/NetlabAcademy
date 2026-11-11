"""
apps.labs.serializers
~~~~~~~~~~~~~~~~~~~~~
DRF serializers for the labs / simulation API.
"""

from __future__ import annotations

from rest_framework import serializers


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
