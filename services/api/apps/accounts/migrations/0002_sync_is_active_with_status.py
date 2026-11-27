"""
Make ``status`` the source of truth for sign-in: set ``is_active`` from
``status`` for existing users (User.save() keeps them in sync from now on).
"""

from django.db import migrations


def sync_is_active(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(status="active").update(is_active=True)
    User.objects.exclude(status="active").update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(sync_is_active, migrations.RunPython.noop),
    ]
