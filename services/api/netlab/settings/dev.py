"""
netlab.settings.dev
~~~~~~~~~~~~~~~~~~~
Development overrides.  Never use in production.
"""

from .base import *  # noqa: F401, F403

DEBUG = True

# Allow DRF browsable API in development.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# Relax host check for local development.
ALLOWED_HOSTS = ["*"]
