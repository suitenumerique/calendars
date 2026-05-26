"""Admin classes and registrations for core app."""

import secrets

from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse

from . import models


@admin.register(models.User)
class UserAdmin(auth_admin.UserAdmin):
    """Admin class for the User model"""

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "admin_email",
                    "password",
                )
            },
        ),
        (
            "Personal info",
            {
                "fields": (
                    "sub",
                    "email",
                    "full_name",
                    "language",
                    "timezone",
                    "organization",
                    "claims",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_device",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "organization", "password1", "password2"),
            },
        ),
    )
    list_display = (
        "id",
        "sub",
        "full_name",
        "admin_email",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
        "is_device",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_staff", "is_superuser", "is_device", "is_active")
    ordering = (
        "is_active",
        "-is_superuser",
        "-is_staff",
        "-is_device",
        "-updated_at",
        "full_name",
    )
    readonly_fields = (
        "id",
        "sub",
        "email",
        "full_name",
        "claims",
        "created_at",
        "updated_at",
    )
    search_fields = ("id", "sub", "admin_email", "email", "full_name")
    raw_id_fields = ("organization",)


@admin.register(models.Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin class for Organization model."""

    list_display = ("name", "external_id", "default_sharing_level", "created_at")
    list_filter = ("default_sharing_level",)
    search_fields = ("name", "external_id")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(models.Channel)
class ChannelAdmin(admin.ModelAdmin):
    """Admin class for Channel model."""

    list_display = (
        "name",
        "type",
        "organization",
        "user",
        "caldav_path",
        "is_active",
        "last_used_at",
        "created_at",
    )
    list_filter = ("type", "scope_level", "is_active")
    search_fields = ("name", "user__email", "caldav_path")
    exclude = ("encrypted_settings",)
    readonly_fields = ("id", "created_at", "updated_at", "last_used_at")
    raw_id_fields = ("user", "organization")
    actions = ("regenerate_tokens",)
    change_form_template = "admin/core/channel/change_form.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<uuid:object_id>/rotate-token/",
                self.admin_site.admin_view(self.rotate_token_view),
                name="core_channel_rotate_token",
            ),
        ]
        return custom + urls

    def rotate_token_view(self, request, object_id):
        """Rotate a single channel's token from the change form button.

        POST-only: rotating mutates state, so we don't expose a GET handler.
        Renders the same success template as the bulk action so the new
        token is shown exactly once.
        """
        if request.method != "POST":
            return HttpResponseRedirect(
                reverse("admin:core_channel_change", args=[object_id])
            )
        channel = get_object_or_404(models.Channel, pk=object_id)
        token, password = self._rotate_one(channel)
        context = {
            **self.admin_site.each_context(request),
            "title": "Regenerated channel tokens",
            "results": [(channel, token, password)],
        }
        return TemplateResponse(
            request, "admin/core/channel/regenerated_tokens.html", context
        )

    @staticmethod
    def _rotate_one(channel):
        """Mint a new token for one channel and return (token, caldav_password).

        ``caldav_password`` is ``base64url(channel_id) + token`` for CalDAV
        channels (the HTTP Basic Auth password), and ``None`` otherwise.
        """
        token = secrets.token_urlsafe(16)
        channel.encrypted_settings = {
            **channel.encrypted_settings,
            "token": token,
        }
        channel.save(update_fields=["encrypted_settings", "updated_at"])
        password = None
        if channel.type == "caldav":
            short_id = models.uuid_to_urlsafe(channel.pk)
            password = f"{short_id}{token}"
        return token, password

    @admin.action(description="Regenerate token for selected channels")
    def regenerate_tokens(self, request, queryset):
        """Regenerate the token for each selected channel.

        New tokens are rendered directly on a success page (not via the
        messages framework, which would persist them in the session cookie).
        They cannot be retrieved afterwards since ``encrypted_settings`` is
        not exposed in the admin.

        For CalDAV channels the full HTTP Basic Auth password
        (``base64url(channel_id)`` concatenated with ``token``) is shown
        alongside the raw token.
        """
        results = [(channel, *self._rotate_one(channel)) for channel in queryset]
        context = {
            **self.admin_site.each_context(request),
            "title": "Regenerated channel tokens",
            "results": results,
        }
        return TemplateResponse(
            request, "admin/core/channel/regenerated_tokens.html", context
        )
