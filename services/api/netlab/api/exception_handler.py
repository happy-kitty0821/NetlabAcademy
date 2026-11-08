"""
netlab.api.exception_handler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Custom DRF exception handler that returns consistent JSON error responses.

Format:
    {
        "error": {
            "code": "validation_error",
            "message": "...",
            "detail": { ... }   # optional field-level detail
        }
    }
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        return None

    error_code = "error"
    if response.status_code == status.HTTP_400_BAD_REQUEST:
        error_code = "validation_error"
    elif response.status_code == status.HTTP_401_UNAUTHORIZED:
        error_code = "authentication_required"
    elif response.status_code == status.HTTP_403_FORBIDDEN:
        error_code = "permission_denied"
    elif response.status_code == status.HTTP_404_NOT_FOUND:
        error_code = "not_found"
    elif response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        error_code = "rate_limit_exceeded"

    data = response.data

    # Normalise to our envelope format.
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        # Simple {"detail": "..."} — flatten to message.
        response.data = {
            "error": {
                "code": error_code,
                "message": str(data["detail"]),
            }
        }
    elif isinstance(data, dict):
        response.data = {
            "error": {
                "code": error_code,
                "message": "One or more fields failed validation.",
                "detail": data,
            }
        }
    else:
        response.data = {
            "error": {
                "code": error_code,
                "message": str(data),
            }
        }

    return response
