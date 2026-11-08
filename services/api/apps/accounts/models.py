"""
apps.accounts.models
~~~~~~~~~~~~~~~~~~~~
Custom User model and related domain objects.

Uses UUID primary keys on all externally-exposed models (per PROJECT_SPEC §8).
The custom User extends AbstractBaseUser so we control every field and avoid
Django's default username-centric design (email is the login identifier).
"""

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    """Platform roles enforced server-side on every API request."""
    ADMIN = "admin", "Administrator"
    INSTRUCTOR = "instructor", "Instructor"
    STUDENT = "student", "Student"


class AccountStatus(models.TextChoices):
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    ARCHIVED = "archived", "Archived"


class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str = None, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault("role", Role.STUDENT)
        extra_fields.setdefault("status", AccountStatus.ACTIVE)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields["role"] = Role.ADMIN
        extra_fields["status"] = AccountStatus.ACTIVE
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Platform user.

    Login identifier: email (not username).
    Role is stored directly on the user for simplicity at this stage;
    object-level permissions are enforced in views and serializers.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    status = models.CharField(
        max_length=20, choices=AccountStatus.choices, default=AccountStatus.ACTIVE
    )

    # Django admin and staff access
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_instructor(self) -> bool:
        return self.role == Role.INSTRUCTOR

    @property
    def is_student(self) -> bool:
        return self.role == Role.STUDENT


class UserProfile(models.Model):
    """
    Extended profile data, separated from the auth User to keep the login
    path lean and allow profile fields to evolve independently.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    timezone = models.CharField(max_length=64, default="UTC")
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    bio = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Profile"

    def __str__(self) -> str:
        return f"Profile({self.user.email})"
