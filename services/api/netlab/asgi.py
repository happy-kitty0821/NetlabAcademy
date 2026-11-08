"""ASGI entry point for the NetLab Academy API (future Channels support)."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "netlab.settings.dev")

application = get_asgi_application()
