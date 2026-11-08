"""
netlab.settings.prod
~~~~~~~~~~~~~~~~~~~~
Production overrides.

Additional hardening (HSTS, SECURE_SSL_REDIRECT, etc.) should be
reviewed before deployment.  See Django deployment checklist.
"""

from .base import *  # noqa: F401, F403

DEBUG = False

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
