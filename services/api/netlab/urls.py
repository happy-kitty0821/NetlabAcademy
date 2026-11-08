"""
netlab.urls
~~~~~~~~~~~
Root URL configuration for the NetLab Academy API.

All application routes are prefixed with /api/v1/.
Authentication routes live under /api/v1/auth/.
"""

from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse


def health(request):
    """Simple liveness probe endpoint."""
    return JsonResponse({"status": "ok", "service": "netlab-api"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/", include("netlab.api.urls")),
]
