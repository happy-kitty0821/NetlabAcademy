"""
apps.labs.urls
~~~~~~~~~~~~~~
URL routing for the labs / simulation API.
"""

from django.urls import path

from .views import (
    SimulationDetailView,
    SimulationDeviceStateView,
    SimulationListCreateView,
    SimulationPingView,
    SimulationResetView,
    SimulationTraceView,
    SimulationCLIView,
)

urlpatterns = [
    # ── Simulation sessions ───────────────────────────────────────────
    path("simulations/", SimulationListCreateView.as_view(), name="sim-list-create"),
    path("simulations/<str:session_id>/", SimulationDetailView.as_view(), name="sim-detail"),
    path("simulations/<str:session_id>/ping/", SimulationPingView.as_view(), name="sim-ping"),
    path("simulations/<str:session_id>/trace/", SimulationTraceView.as_view(), name="sim-trace"),
    path("simulations/<str:session_id>/reset/", SimulationResetView.as_view(), name="sim-reset"),
    path("simulations/<str:session_id>/cli/", SimulationCLIView.as_view(), name="sim-cli"),
    path(
        "simulations/<str:session_id>/devices/<str:device_id>/",
        SimulationDeviceStateView.as_view(),
        name="sim-device-state",
    ),
]
