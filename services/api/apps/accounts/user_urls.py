"""
apps.accounts.user_urls
~~~~~~~~~~~~~~~~~~~~~~~
Administrator user management, mounted at /api/v1/users/.
"""

from django.urls import path

from .views import UserDetailView, UserListCreateView

urlpatterns = [
    path("", UserListCreateView.as_view(), name="user-list"),
    path("<uuid:user_id>/", UserDetailView.as_view(), name="user-detail"),
]
