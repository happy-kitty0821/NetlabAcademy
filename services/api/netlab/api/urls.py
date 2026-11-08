"""
netlab.api.urls
~~~~~~~~~~~~~~~
API v1 route registry.

Each domain app registers its own router; this module aggregates them
under /api/v1/.
"""

from django.urls import include, path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

urlpatterns = [
    # ── Authentication ─────────────────────────────────────────────
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    # ── Domain apps ────────────────────────────────────────────────
    path("auth/", include("apps.accounts.urls")),
    path("courses/", include("apps.courses.urls")),
    path("labs/", include("apps.labs.urls")),
]
