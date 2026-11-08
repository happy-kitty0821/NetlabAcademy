"""
apps.accounts.serializers
~~~~~~~~~~~~~~~~~~~~~~~~~
DRF serializers for user registration, login response and profile.

The correct answer (e.g. password, hidden fields) is never returned
in any response serializer.
"""

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User, UserProfile


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
