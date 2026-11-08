"""
apps.accounts.views
~~~~~~~~~~~~~~~~~~~
Account management API views.

All views enforce server-side authorization — no reliance on frontend
route guards.
"""

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User, UserProfile
from .serializers import UserRegistrationSerializer, UserSerializer, UserUpdateSerializer


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
