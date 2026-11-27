"""
apps.labs.views
~~~~~~~~~~~~~~
API views for simulation sessions and device CLI.
"""

from __future__ import annotations

from rest_framework import generics
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from simulator_core import ConfigurationError, TopologyError

from .models import Lab
from .serializers import (
    LabListSerializer,
    LabSerializer,
    PingRequestSerializer,
    TopologyDocumentSerializer,
)
from .services import simulation_adapter as adapter


# ── Simulation lifecycle ──────────────────────────────────────────────────────

class SimulationListCreateView(APIView):
    """POST /api/v1/labs/simulations/ — create a new simulation session."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TopologyDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            session = adapter.create_session(
                serializer.validated_data,
                seed=request.data.get("seed", 42),
            )
        except (ConfigurationError, TopologyError) as exc:
            return Response(
                {"error": {"code": "topology_error", "message": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "id": session.id,
                "seed": session.seed,
                "clock": session.simulation.clock,
                "device_count": len(session.simulation.topology.devices),
                "link_count": len(session.simulation.topology.links),
            },
            status=status.HTTP_201_CREATED,
        )


class SimulationDetailView(APIView):
    """GET / DELETE /api/v1/labs/simulations/<id>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id: str):
        try:
            session = adapter.get_session(session_id)
        except KeyError:
            return Response(
                {"error": {"code": "not_found", "message": "Simulation session not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({
            "id": session.id,
            "seed": session.seed,
            "clock": session.simulation.clock,
            "device_count": len(session.simulation.topology.devices),
            "link_count": len(session.simulation.topology.links),
            "trace_length": len(session.simulation.trace),
        })

    def delete(self, request, session_id: str):
        adapter.delete_session(session_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SimulationPingView(APIView):
    """POST /api/v1/labs/simulations/<id>/ping/ — issue a ping."""

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id: str):
        try:
            session = adapter.get_session(session_id)
        except KeyError:
            return Response(
                {"error": {"code": "not_found", "message": "Simulation session not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = PingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = adapter.run_ping(
                session,
                device_id=data["device_id"],
                target_ip=data["target_ip"],
                count=data["count"],
            )
        except ConfigurationError as exc:
            return Response(
                {"error": {"code": "configuration_error", "message": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except KeyError as exc:
            return Response(
                {"error": {"code": "not_found", "message": str(exc)}},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(result)


class SimulationTraceView(APIView):
    """GET /api/v1/labs/simulations/<id>/trace/ — get the event trace."""

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id: str):
        try:
            session = adapter.get_session(session_id)
        except KeyError:
            return Response(
                {"error": {"code": "not_found", "message": "Simulation session not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"trace": adapter.get_trace(session)})


class SimulationDeviceStateView(APIView):
    """GET /api/v1/labs/simulations/<id>/devices/<device_id>/ — get device state."""

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id: str, device_id: str):
        try:
            session = adapter.get_session(session_id)
        except KeyError:
            return Response(
                {"error": {"code": "not_found", "message": "Simulation session not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            state = adapter.get_device_state(session, device_id)
        except KeyError as exc:
            return Response(
                {"error": {"code": "not_found", "message": str(exc)}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(state)


class SimulationResetView(APIView):
    """POST /api/v1/labs/simulations/<id>/reset/ — reset the simulation."""

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id: str):
        try:
            session = adapter.get_session(session_id)
        except KeyError:
            return Response(
                {"error": {"code": "not_found", "message": "Simulation session not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        result = adapter.reset_session(session)
        return Response(result)


# ── CLI ───────────────────────────────────────────────────────────────────────

class CLICommandSerializer(drf_serializers.Serializer):
    """Request body for a CLI command."""
    device_id = drf_serializers.CharField(max_length=64)
    command   = drf_serializers.CharField(max_length=1024, allow_blank=True)
    action    = drf_serializers.ChoiceField(
        choices=["execute", "complete", "help"],
        default="execute",
    )


class SimulationCLIView(APIView):
    """
    POST /api/v1/labs/simulations/<id>/cli/

    Execute, tab-complete, or get help for a CLI command on a device.

    Actions:
      execute  — run the command, return output + prompt + mode
      complete — tab-complete the partial input, return completed string
      help     — return context-sensitive ? help for the partial input

    Request:  { "device_id": "host-a", "command": "sh ip int b", "action": "complete" }
    Response (execute):  { "output": "...", "prompt": "PC-A>", "mode": "user_exec",
                           "awaiting_input": false, "input_hidden": false }
      awaiting_input — the device is reading the next line itself (Password:,
                       Username:, Destination filename?, Press RETURN); the
                       terminal must send it even when empty.
      input_hidden   — do not echo the next line (password prompts).
    Response (complete): { "completed": "show ip interface brief", "prompt": "PC-A>" }
    Response (help):      { "help": "...", "prompt": "PC-A>" }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id: str):
        try:
            session = adapter.get_session(session_id)
        except KeyError:
            return Response(
                {"error": {"code": "not_found", "message": "Simulation session not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CLICommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data["device_id"]
        command   = serializer.validated_data["command"]
        action    = serializer.validated_data["action"]

        try:
            cli_session = adapter.get_or_create_cli_session(session, device_id)
        except KeyError as exc:
            return Response(
                {"error": {"code": "not_found", "message": str(exc)}},
                status=status.HTTP_404_NOT_FOUND,
            )

        if action == "complete":
            completed = cli_session.complete(command)
            return Response({
                "completed": completed,
                "prompt": cli_session.prompt(),
            })

        if action == "help":
            # The ? help is handled by execute() when the input ends with ?
            help_text = cli_session.execute(command + "?") if not command.endswith("?") else cli_session.execute(command)
            return Response({
                "help": help_text,
                "prompt": cli_session.prompt(),
            })

        # Default: execute
        output = cli_session.execute(command)
        return Response({
            "output": output,
            "prompt": cli_session.prompt(),
            "mode":   cli_session.mode.name.lower(),
            "awaiting_input": cli_session.pending_input is not None,
            "input_hidden":   cli_session.input_hidden,
        })


# ── Lab persistence (CRUD) ─────────────────────────────────────────────────────


class LabListCreateView(generics.ListCreateAPIView):
    """GET / POST /api/v1/labs/labs/

    Lists the caller's labs as a plain array (pagination disabled) and
    creates a new lab owned by the caller. The list endpoint uses the
    compact ``LabListSerializer`` (no topology payload, with device/link
    counts); writes use the full ``LabSerializer``.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return Lab.objects.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.request.method == "GET":
            return LabListSerializer
        return LabSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class LabDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE /api/v1/labs/labs/<lab_id>/"""

    permission_classes = [IsAuthenticated]
    serializer_class = LabSerializer
    lookup_url_kwarg = "lab_id"
    lookup_field = "id"

    def get_queryset(self):
        return Lab.objects.filter(owner=self.request.user)
