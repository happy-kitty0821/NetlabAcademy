"""
apps.labs.urls
~~~~~~~~~~~~~~
URL routing for the labs / simulation API.
"""

from django.urls import path

from .views import (
    LabDetailView,
    LabListCreateView,
    SimulationDetailView,
    SimulationDeviceStateView,
    SimulationListCreateView,
    SimulationPingView,
    SimulationResetView,
    SimulationTraceView,
    SimulationCLIView,
    SimulationConsoleView,
    SimulationLinkDetailView,
    SimulationLinksView,
    SimulationSyslogView,
)

urlpatterns = [
    # ── Lab persistence ───────────────────────────────────────────────
    path("labs/", LabListCreateView.as_view(), name="lab-list-create"),
    path("labs/<uuid:lab_id>/", LabDetailView.as_view(), name="lab-detail"),

    # ── Simulation sessions ───────────────────────────────────────────
    path("simulations/", SimulationListCreateView.as_view(), name="sim-list-create"),
    path("simulations/<str:session_id>/", SimulationDetailView.as_view(), name="sim-detail"),
    path("simulations/<str:session_id>/ping/", SimulationPingView.as_view(), name="sim-ping"),
    path("simulations/<str:session_id>/trace/", SimulationTraceView.as_view(), name="sim-trace"),
    path("simulations/<str:session_id>/reset/", SimulationResetView.as_view(), name="sim-reset"),
    path("simulations/<str:session_id>/cli/", SimulationCLIView.as_view(), name="sim-cli"),
    path("simulations/<str:session_id>/console/<str:device_id>/", SimulationConsoleView.as_view(), name="sim-console"),
    path("simulations/<str:session_id>/syslog/", SimulationSyslogView.as_view(), name="sim-syslog"),
    path("simulations/<str:session_id>/links/", SimulationLinksView.as_view(), name="sim-links"),
    path("simulations/<str:session_id>/links/<str:link_id>/", SimulationLinkDetailView.as_view(), name="sim-link-detail"),
    path(
        "simulations/<str:session_id>/devices/<str:device_id>/",
        SimulationDeviceStateView.as_view(),
        name="sim-device-state",
    ),
]
