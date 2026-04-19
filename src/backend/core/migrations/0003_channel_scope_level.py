"""Add scope_level field and scopes to Channel, replacing role-based access."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


ROLE_TO_SCOPES = {
    "reader": ["calendars:read", "events:read"],
    "editor": ["calendars:read", "events:read", "events:write"],
    "admin": [
        "calendars:read",
        "events:read",
        "events:write",
        "calendars:write",
    ],
}


def forwards(apps, schema_editor):
    """Convert settings.role → settings.scopes and infer scope_level."""
    Channel = apps.get_model("core", "Channel")
    for channel in Channel.objects.all():
        role = channel.settings.get("role", "reader")
        channel.settings["scopes"] = ROLE_TO_SCOPES.get(
            role, ["calendars:read"]
        )
        if channel.caldav_path:
            channel.scope_level = "calendar"
        elif channel.user_id:
            channel.scope_level = "user"
        else:
            channel.scope_level = "global"
        channel.save(update_fields=["settings", "scope_level"])


def backwards(apps, schema_editor):
    """Convert settings.scopes back to settings.role."""
    Channel = apps.get_model("core", "Channel")
    for channel in Channel.objects.all():
        scopes = set(channel.settings.get("scopes", []))
        if "calendars:write" in scopes:
            channel.settings["role"] = "admin"
        elif "events:write" in scopes:
            channel.settings["role"] = "editor"
        else:
            channel.settings["role"] = "reader"
        channel.save(update_fields=["settings"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_organization_default_sharing_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="scope_level",
            field=models.CharField(
                db_index=True,
                default="user",
                help_text=(
                    "Access scope: global (instance-wide), user,"
                    " or calendar."
                ),
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AddConstraint(
            model_name="channel",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(scope_level="global")
                    | models.Q(scope_level="user", user__isnull=False)
                    | (
                        models.Q(
                            scope_level="calendar", user__isnull=False
                        )
                        & models.Q(caldav_path__isnull=False)
                        & ~models.Q(caldav_path="")
                    )
                ),
                name="channel_scope_level_targets",
            ),
        ),
        migrations.AlterField(
            model_name="channel",
            name="settings",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Channel-specific configuration settings (e.g. scopes).",
                verbose_name="settings",
            ),
        ),
        migrations.AlterField(
            model_name="channel",
            name="user",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Target user (scope_level=user/calendar) or audit"
                    " creator (global)."
                ),
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="channels",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
