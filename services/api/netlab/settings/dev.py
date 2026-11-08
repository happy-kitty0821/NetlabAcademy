"""
netlab.settings.dev
~~~~~~~~~~~~~~~~~~~
Development overrides.  Never use in production.

Uses SQLite so no PostgreSQL installation is required during development.
Switch to prod.py (PostgreSQL) before deploying.
"""

from pathlib import Path
from .base import *  # noqa: F401, F403

DEBUG = True

# ── SQLite for development ────────────────────────────────────────────────────
# Overrides the PostgreSQL config in base.py.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(__file__).resolve().parent.parent.parent / "db.sqlite3",
    }
}

# Allow DRF browsable API in development.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# Relax host check for local development.
ALLOWED_HOSTS = ["*"]
