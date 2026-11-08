"""WSGI entry point for the NetLab Academy API."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "netlab.settings.dev")

application = get_wsgi_application()
