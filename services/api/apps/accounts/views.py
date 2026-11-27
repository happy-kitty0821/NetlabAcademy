"""
apps.accounts.views
~~~~~~~~~~~~~~~~~~~
Account management API views.

All views enforce server-side authorization — no reliance on frontend
route guards.
"""

from django.db.models import Q
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import User, UserProfile
from .permissions import IsPlatformAdmin
from .serializers import (
    AdminUserCreateSerializer,
    AdminUserSerializer,
    NetlabTokenObtainPairSerializer,
    NetlabTokenRefreshSerializer,
    UserRegistrationSerializer,
    UserSerializer,
    UserUpdateSerializer,
)


class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/token/

    Email + password → access/refresh JWTs (with role/status claims).
    Only ACTIVE accounts can sign in.
    """

    serializer_class = NetlabTokenObtainPairSerializer


class RefreshView(TokenRefreshView):
    """POST /api/v1/auth/token/refresh/ — refused for inactive accounts."""

    serializer_class = NetlabTokenRefreshSerializer


class RegisterView(generics.CreateAPIView):
    """
    POST /api/v1/auth/register/

    Public endpoint.  Creates a student account and returns the user object.
    Does not auto-login — client must call the token endpoint separately.
    """

    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # Create a default profile.
        UserProfile.objects.get_or_create(user=user)
        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


class MeView(APIView):
    """
    GET  /api/v1/auth/me/   — return the authenticated user's own data.
    PATCH /api/v1/auth/me/  — update name fields.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Administrator user management — /api/v1/users/
# ---------------------------------------------------------------------------

class UserListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/users/?role=&status=&search=   — list users (admin only)
    POST /api/v1/users/                          — create a user with any role
    """

    permission_classes = [IsPlatformAdmin]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return AdminUserCreateSerializer
        return AdminUserSerializer

    def get_queryset(self):
        qs = User.objects.all().order_by("email")
        params = self.request.query_params
        if params.get("role"):
            qs = qs.filter(role=params["role"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("search"):
            term = params["search"]
            qs = qs.filter(
                Q(email__icontains=term)
                | Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
            )
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(AdminUserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserDetailView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/users/<id>/  — one user (admin only)
    PATCH /api/v1/users/<id>/  — change names, role or status

    Accounts are never deleted through the API; set status to "archived".
    """

    permission_classes = [IsPlatformAdmin]
    serializer_class = AdminUserSerializer
    queryset = User.objects.all()
    lookup_url_kwarg = "user_id"
    http_method_names = ["get", "patch", "head", "options"]
