"""
python manage.py create_admin --email admin@example.com [--first-name A --last-name B]

Creates a platform administrator, or promotes an existing user to one.

The password is prompted for interactively (never echoed, never stored in
configuration files).  For scripts, pass --no-input together with
--password; avoid that on shared machines because the password can end up
in shell history.

Administrators get role=admin, status=active and access to the Django admin
site (is_staff / is_superuser).
"""

from __future__ import annotations

import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import AccountStatus, Role, User, UserProfile


class Command(BaseCommand):
    help = "Create a platform administrator, or promote an existing user to one."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")
        parser.add_argument(
            "--password",
            help="Only with --no-input (scripts/CI). Prompted for otherwise.",
        )
        parser.add_argument(
            "--no-input", action="store_true",
            help="Do not prompt; requires --password when creating a new user.",
        )

    def _read_password(self, options, required: bool) -> str | None:
        if options["password"]:
            return options["password"]
        if options["no_input"]:
            if required:
                raise CommandError("--password is required with --no-input for a new user.")
            return None
        prompt_hint = "" if required else " (leave blank to keep the current password)"
        while True:
            first = getpass.getpass(f"Password{prompt_hint}: ")
            if not first and not required:
                return None
            second = getpass.getpass("Password (again): ")
            if first != second:
                self.stderr.write("Passwords do not match. Try again.")
                continue
            return first

    @transaction.atomic
    def handle(self, *args, **options):
        email = User.objects.normalize_email(options["email"].strip())
        if not email:
            raise CommandError("An email address is required.")
        user = User.objects.filter(email__iexact=email).first()
        password = self._read_password(options, required=user is None)

        if password is not None:
            try:
                validate_password(password, user=user)
            except ValidationError as exc:
                raise CommandError("Password rejected: " + " ".join(exc.messages)) from exc

        if user is None:
            user = User.objects.create_superuser(
                email=email,
                password=password,
                first_name=options["first_name"],
                last_name=options["last_name"],
            )
            UserProfile.objects.get_or_create(user=user)
            self.stdout.write(self.style.SUCCESS(f"Created administrator {user.email}."))
            return

        was_admin = user.role == Role.ADMIN and user.status == AccountStatus.ACTIVE
        user.role = Role.ADMIN
        user.status = AccountStatus.ACTIVE
        user.is_staff = True
        user.is_superuser = True
        if options["first_name"]:
            user.first_name = options["first_name"]
        if options["last_name"]:
            user.last_name = options["last_name"]
        if password is not None:
            user.set_password(password)
        user.save()
        UserProfile.objects.get_or_create(user=user)
        if was_admin:
            self.stdout.write(f"{user.email} was already an administrator; details updated.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Promoted {user.email} to administrator."))
