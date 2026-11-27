"""
apps.accounts.serializers
~~~~~~~~~~~~~~~~~~~~~~~~~
DRF serializers for user registration, login response and profile.

The correct answer (e.g. password, hidden fields) is never returned
in any response serializer.
"""

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from .models import AccountStatus, Role, User, UserProfile


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Accepts the minimum fields needed to create a student account."""

    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "password", "password_confirm"]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["timezone", "bio", "avatar"]


class UserSerializer(serializers.ModelSerializer):
    """Safe read-only representation of a user (no password, no sensitive fields)."""

    full_name = serializers.CharField(read_only=True)
    profile = UserProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "full_name",
            "role", "status", "date_joined", "profile",
        ]
        read_only_fields = ["id", "role", "status", "date_joined"]


class UserUpdateSerializer(serializers.ModelSerializer):
    """Allows a user to update their own non-sensitive fields."""

    class Meta:
        model = User
        fields = ["first_name", "last_name"]


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

class NetlabTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Login: issues access/refresh tokens for an ACTIVE account.

    The tokens carry ``email``, ``role`` and ``status`` claims so the
    frontend can shape its UI without an extra request.  The claims are
    informational only: the API always authorizes from the database user.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["role"] = user.role
        token["status"] = user.status
        return token


class NetlabTokenRefreshSerializer(TokenRefreshSerializer):
    """Refuses to refresh tokens for accounts that are no longer active."""

    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh.payload.get("user_id")
        user = User.objects.filter(pk=user_id).first()
        if user is None or not user.is_active:
            raise serializers.ValidationError(
                {"refresh": "This account is not active."}, code="account_inactive"
            )
        return super().validate(attrs)


# ---------------------------------------------------------------------------
# Administrator user management
# ---------------------------------------------------------------------------

class AdminUserSerializer(serializers.ModelSerializer):
    """
    A user as seen and edited by a platform administrator.

    Editable: names, role and status.  Guard rails (checked in ``update``):
    an administrator cannot demote or deactivate themselves, and the last
    active administrator cannot be demoted or deactivated.
    """

    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "full_name",
            "role", "status", "date_joined", "last_login",
        ]
        read_only_fields = ["id", "email", "date_joined", "last_login"]

    def update(self, instance, validated_data):
        acting = self.context["request"].user
        new_role = validated_data.get("role", instance.role)
        new_status = validated_data.get("status", instance.status)
        loses_admin = (
            instance.role == Role.ADMIN
            and instance.status == AccountStatus.ACTIVE
            and (new_role != Role.ADMIN or new_status != AccountStatus.ACTIVE)
        )
        if loses_admin and instance.pk == acting.pk:
            raise serializers.ValidationError(
                {"role": "You cannot remove your own administrator access."}
            )
        with transaction.atomic():
            if loses_admin:
                others = (
                    User.objects.select_for_update()
                    .filter(role=Role.ADMIN, status=AccountStatus.ACTIVE)
                    .exclude(pk=instance.pk)
                )
                if not others.exists():
                    raise serializers.ValidationError(
                        {"role": "At least one active administrator is required."}
                    )
            return super().update(instance, validated_data)


class AdminUserCreateSerializer(serializers.ModelSerializer):
    """An administrator creates an account with any role (e.g. instructors)."""

    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "role", "status", "password"]
        read_only_fields = ["id"]

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        UserProfile.objects.get_or_create(user=user)
        return user
