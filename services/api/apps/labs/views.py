"""
apps.labs.views
~~~~~~~~~~~~~~
API views for simulation sessions.

Endpoints:
  POST   /api/v1/labs/simulations/           — create a simulation from a topology
  GET    /api/v1/labs/simulations/<id>/      — get session status
  DELETE /api/v1/labs/simulations/<id>/       — delete session
  POST   /api/v1/labs/simulations/<id>/ping/  — issue a ping from a device
  GET    /api/v1/labs/simulations/<id>/trace/ — get the event trace
  GET    /api/v1/labs/simulations/<id>/devices/<id>/ — get device state
  POST   /api/v1/labs/simulations/<id>/reset/ — reset the simulation
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from simulator_core import ConfigurationError, TopologyError

from .serializers import PingRequestSerializer, TopologyDocumentSerializer
from .services import simulation_adapter as adapter


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
