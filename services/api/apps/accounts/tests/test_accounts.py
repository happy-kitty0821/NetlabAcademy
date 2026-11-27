"""
apps.accounts.tests.test_accounts
---------------------------------
Persistent users with roles: registration, login (JWT with role claims),
status-controlled sign-in, role permissions, administrator user management
and the create_admin command.
"""

from __future__ import annotations

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import AccountStatus, Role, User, UserProfile
from apps.accounts.permissions import IsInstructorOrAdmin, IsPlatformAdmin, role_required

PASSWORD = "Str0ng-Lab-Passw0rd!"


def make_user(email: str, role: str = Role.STUDENT, status: str = AccountStatus.ACTIVE) -> User:
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name="Test", last_name=role.title(),
        role=role, status=status,
    )


def login(client: APIClient, email: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/token/", {"email": email, "password": password}, format="json")


class RegistrationTests(TestCase):
    def test_registration_creates_persistent_student(self):
        client = APIClient()
        res = client.post("/api/v1/auth/register/", {
            "email": "New.Student@Example.com", "first_name": "New", "last_name": "Student",
            "password": PASSWORD, "password_confirm": PASSWORD,
            "role": "admin",   # must be ignored
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        user = User.objects.get(email__iexact="new.student@example.com")
        self.assertEqual(user.role, Role.STUDENT)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertEqual(res.json()["role"], "student")


class LoginTests(TestCase):
    def test_login_returns_tokens_with_role_claims(self):
        make_user("teacher@example.com", role=Role.INSTRUCTOR)
        res = login(APIClient(), "teacher@example.com")
        self.assertEqual(res.status_code, 200, res.content)
        claims = AccessToken(res.json()["access"])
        self.assertEqual(claims["role"], "instructor")
        self.assertEqual(claims["status"], "active")
        self.assertEqual(claims["email"], "teacher@example.com")

    def test_wrong_password_rejected(self):
        make_user("s@example.com")
        self.assertEqual(login(APIClient(), "s@example.com", "wrong").status_code, 401)

    def test_inactive_statuses_cannot_sign_in(self):
        for status in (AccountStatus.SUSPENDED, AccountStatus.ARCHIVED, AccountStatus.INVITED):
            make_user(f"{status}@example.com", status=status)
            user = User.objects.get(email=f"{status}@example.com")
            self.assertFalse(user.is_active, status)
            self.assertEqual(login(APIClient(), user.email).status_code, 401, status)

    def test_suspension_invalidates_existing_tokens(self):
        user = make_user("later-suspended@example.com")
        client = APIClient()
        tokens = login(client, user.email).json()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 200)

        user.status = AccountStatus.SUSPENDED
        user.save()
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 401)
        refresh = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertIn(refresh.status_code, (400, 401))

    def test_me_returns_role_and_status(self):
        make_user("me@example.com", role=Role.INSTRUCTOR)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login(client, 'me@example.com').json()['access']}")
        body = client.get("/api/v1/auth/me/").json()
        self.assertEqual((body["role"], body["status"]), ("instructor", "active"))

    def test_user_cannot_change_own_role_via_me(self):
        user = make_user("sneaky@example.com")
        client = APIClient()
        client.force_authenticate(user=user)
        client.patch("/api/v1/auth/me/", {"role": "admin", "first_name": "Sam"}, format="json")
        user.refresh_from_db()
        self.assertEqual(user.role, Role.STUDENT)
        self.assertEqual(user.first_name, "Sam")


class StatusSyncTests(TestCase):
    def test_is_active_follows_status_with_update_fields(self):
        user = make_user("sync@example.com")
        user.status = AccountStatus.SUSPENDED
        user.save(update_fields=["status"])
        user.refresh_from_db()
        self.assertFalse(user.is_active)


class PermissionClassTests(TestCase):
    def _allowed(self, permission, user) -> bool:
        request = APIRequestFactory().get("/")
        request.user = user
        return permission().has_permission(request, None)

    def test_role_permissions(self):
        admin = make_user("a@example.com", role=Role.ADMIN)
        teacher = make_user("t@example.com", role=Role.INSTRUCTOR)
        student = make_user("s@example.com")
        self.assertEqual([self._allowed(IsPlatformAdmin, u) for u in (admin, teacher, student)],
                         [True, False, False])
        self.assertEqual([self._allowed(IsInstructorOrAdmin, u) for u in (admin, teacher, student)],
                         [True, True, False])
        self.assertTrue(self._allowed(role_required(Role.STUDENT), student))

    def test_inactive_admin_has_no_permissions(self):
        admin = make_user("old-admin@example.com", role=Role.ADMIN, status=AccountStatus.SUSPENDED)
        self.assertFalse(self._allowed(IsPlatformAdmin, admin))


class AdminUserApiTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", role=Role.ADMIN)
        self.student = make_user("student@example.com")
        self.teacher = make_user("teacher@example.com", role=Role.INSTRUCTOR)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_non_admins_are_forbidden(self):
        for user in (self.student, self.teacher):
            client = APIClient()
            client.force_authenticate(user=user)
            self.assertEqual(client.get("/api/v1/users/").status_code, 403)
            self.assertEqual(
                client.patch(f"/api/v1/users/{user.id}/", {"role": "admin"}, format="json").status_code, 403
            )
        self.assertEqual(APIClient().get("/api/v1/users/").status_code, 401)

    def test_list_and_filter_users(self):
        res = self.client.get("/api/v1/users/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 3)
        only_students = self.client.get("/api/v1/users/?role=student").json()["results"]
        self.assertEqual([u["email"] for u in only_students], ["student@example.com"])
        found = self.client.get("/api/v1/users/?search=teach").json()["results"]
        self.assertEqual([u["email"] for u in found], ["teacher@example.com"])

    def test_change_role_and_status(self):
        res = self.client.patch(f"/api/v1/users/{self.student.id}/",
                                {"role": "instructor", "status": "suspended"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.student.refresh_from_db()
        self.assertEqual((self.student.role, self.student.status), (Role.INSTRUCTOR, AccountStatus.SUSPENDED))
        self.assertFalse(self.student.is_active)

    def test_email_is_read_only(self):
        self.client.patch(f"/api/v1/users/{self.student.id}/", {"email": "x@example.com"}, format="json")
        self.student.refresh_from_db()
        self.assertEqual(self.student.email, "student@example.com")

    def test_admin_cannot_demote_self(self):
        res = self.client.patch(f"/api/v1/users/{self.admin.id}/", {"role": "student"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, Role.ADMIN)

    def test_last_active_admin_is_protected(self):
        other = make_user("second-admin@example.com", role=Role.ADMIN)
        # Two active admins: suspending the other one is allowed...
        ok = self.client.patch(f"/api/v1/users/{other.id}/", {"status": "suspended"}, format="json")
        self.assertEqual(ok.status_code, 200)
        # ...after which the acting admin is the only active admin left and
        # cannot archive their own account.
        res = self.client.patch(f"/api/v1/users/{self.admin.id}/", {"status": "archived"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_last_admin_cannot_be_demoted_by_anyone(self):
        other = make_user("second-admin@example.com", role=Role.ADMIN)
        self.client.patch(f"/api/v1/users/{other.id}/", {"role": "student"}, format="json")
        client = APIClient()
        client.force_authenticate(user=User.objects.get(pk=self.admin.pk))
        res = client.patch(f"/api/v1/users/{self.admin.id}/", {"role": "instructor"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_admin_creates_instructor(self):
        res = self.client.post("/api/v1/users/", {
            "email": "new.teacher@example.com", "first_name": "New", "last_name": "Teacher",
            "role": "instructor", "password": PASSWORD,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertNotIn("password", res.json())
        self.assertEqual(login(APIClient(), "new.teacher@example.com").status_code, 200)

    def test_no_delete_endpoint(self):
        res = self.client.delete(f"/api/v1/users/{self.student.id}/")
        self.assertEqual(res.status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.student.pk).exists())


class CreateAdminCommandTests(TestCase):
    def test_creates_new_admin(self):
        out = StringIO()
        call_command("create_admin", "--email", "root@example.com", "--no-input",
                     "--password", PASSWORD, stdout=out)
        user = User.objects.get(email="root@example.com")
        self.assertEqual((user.role, user.status), (Role.ADMIN, AccountStatus.ACTIVE))
        self.assertTrue(user.is_staff and user.is_superuser and user.is_active)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertIn("Created administrator", out.getvalue())

    def test_promotes_existing_user_keeping_password(self):
        make_user("promote@example.com", status=AccountStatus.SUSPENDED)
        call_command("create_admin", "--email", "PROMOTE@example.com", "--no-input", stdout=StringIO())
        user = User.objects.get(email="promote@example.com")
        self.assertEqual((user.role, user.status), (Role.ADMIN, AccountStatus.ACTIVE))
        self.assertTrue(user.check_password(PASSWORD))

    def test_new_admin_requires_password_without_input(self):
        with self.assertRaises(CommandError):
            call_command("create_admin", "--email", "nopw@example.com", "--no-input")

    def test_weak_password_rejected(self):
        with self.assertRaises(CommandError):
            call_command("create_admin", "--email", "weak@example.com", "--no-input", "--password", "123")
        self.assertFalse(User.objects.filter(email="weak@example.com").exists())
