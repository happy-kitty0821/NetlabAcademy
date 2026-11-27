"""
apps.accounts.permissions
~~~~~~~~~~~~~~~~~~~~~~~~~
Role-based DRF permission classes.

Authorization always reads the role from the database user attached to the
request (``request.user.role``), never from token claims, so a role change
takes effect on the user's next request.

These are the building blocks for the platform's RBAC rules:

    permission_classes = [IsPlatformAdmin]
    permission_classes = [role_required(Role.INSTRUCTOR, Role.ADMIN)]
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from .models import AccountStatus, Role


class HasRole(BasePermission):
    """Grants access when the authenticated, active user has one of ``roles``."""

    roles: tuple[str, ...] = ()
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.status == AccountStatus.ACTIVE
            and user.role in self.roles
        )


def role_required(*roles: str) -> type[HasRole]:
    """Build a permission class that allows only the given roles."""
    names = "Or".join(r.title() for r in roles)
    return type(f"Is{names}", (HasRole,), {"roles": tuple(roles)})


IsPlatformAdmin = role_required(Role.ADMIN)
IsInstructorOrAdmin = role_required(Role.INSTRUCTOR, Role.ADMIN)
