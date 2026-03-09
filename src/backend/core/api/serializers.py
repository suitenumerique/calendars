"""Client serializers for the calendars core app."""

from django.conf import settings
from django.utils.text import slugify

from rest_framework import serializers

from core import models
from core.entitlements import EntitlementsUnavailableError, get_user_entitlements
from core.models import uuid_to_urlsafe


class OrganizationSerializer(serializers.ModelSerializer):
    """Serialize organizations."""

    class Meta:
        model = models.Organization
        fields = ["id", "name"]
        read_only_fields = ["id", "name"]


class UserLiteSerializer(serializers.ModelSerializer):
    """Serialize users with limited fields."""

    class Meta:
        model = models.User
        fields = ["id", "full_name"]
        read_only_fields = ["id", "full_name"]


class UserSerializer(serializers.ModelSerializer):
    """Serialize users."""

    email = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.User
        fields = [
            "id",
            "email",
            "full_name",
            "language",
        ]
        read_only_fields = ["id", "email", "full_name"]

    def get_email(self, user) -> str | None:
        """Return OIDC email, falling back to admin_email for staff users."""
        return user.email or user.admin_email


class UserMeSerializer(UserSerializer):
    """Serialize users for me endpoint."""

    can_access = serializers.SerializerMethodField(read_only=True)
    can_admin = serializers.SerializerMethodField(read_only=True)
    organization = OrganizationSerializer(read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._entitlements_cache = {}

    class Meta:
        model = models.User
        fields = [
            *UserSerializer.Meta.fields,
            "can_access",
            "can_admin",
            "organization",
        ]
        read_only_fields = [
            *UserSerializer.Meta.read_only_fields,
            "can_access",
            "can_admin",
            "organization",
        ]

    def _get_entitlements(self, user):
        """Get cached entitlements for the user, keyed by user.sub.

        Cache is per-serializer-instance (request-scoped) to avoid
        duplicate calls when both can_access and can_admin are serialized.
        """
        if user.sub not in self._entitlements_cache:
            try:
                self._entitlements_cache[user.sub] = get_user_entitlements(
                    user.sub, user.email
                )
            except EntitlementsUnavailableError:
                self._entitlements_cache[user.sub] = None
        return self._entitlements_cache[user.sub]

    def get_can_access(self, user) -> bool:
        """Check entitlements for the current user."""
        entitlements = self._get_entitlements(user)
        if entitlements is None:
            return False  # fail-closed
        return entitlements.get("can_access", False)

    def get_can_admin(self, user) -> bool:
        """Check admin entitlement for the current user."""
        entitlements = self._get_entitlements(user)
        if entitlements is None:
            return False  # fail-closed
        return entitlements.get("can_admin", False)


class ChannelSerializer(serializers.ModelSerializer):
    """Read serializer for Channel model."""

    role = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = models.Channel
        fields = [
            "id",
            "name",
            "type",
            "organization",
            "user",
            "caldav_path",
            "role",
            "is_active",
            "settings",
            "url",
            "last_used_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_role(self, obj):
        """Get role from settings."""
        return obj.role

    def get_url(self, obj) -> str | None:
        """Build iCal subscription URL for ical-feed channels, None otherwise."""
        if obj.type != "ical-feed":
            return None

        token = obj.encrypted_settings.get("token", "")
        if not token:
            return None

        short_id = uuid_to_urlsafe(obj.pk)
        calendar_name = obj.settings.get("calendar_name", "")
        filename = slugify(calendar_name)[:50] or "feed"
        ical_path = f"/ical/{short_id}/{token}/{filename}.ics"

        request = self.context.get("request")
        if request:
            url = request.build_absolute_uri(ical_path)
        else:
            app_url = settings.APP_URL
            url = f"{app_url.rstrip('/')}{ical_path}"

        if not settings.DEBUG and url.startswith("http://"):
            url = url.replace("http://", "https://", 1)

        return url


class ChannelCreateSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Write serializer for creating a Channel."""

    name = serializers.CharField(max_length=255)
    type = serializers.CharField(max_length=255, default="caldav")
    caldav_path = serializers.CharField(max_length=512, required=False, default="")
    calendar_name = serializers.CharField(max_length=255, required=False, default="")
    role = serializers.ChoiceField(
        choices=[(r, r) for r in models.Channel.VALID_ROLES],
        default=models.Channel.ROLE_READER,
    )

    def validate_caldav_path(self, value):
        """Normalize caldav_path if provided."""
        if value:
            if not value.endswith("/"):
                value = value + "/"
            if not value.startswith("/"):
                value = "/" + value
        return value

    def validate_type(self, value):
        """Validate channel type."""
        if value == "ical-feed":
            return value
        return "caldav"


class ChannelWithTokenSerializer(ChannelSerializer):
    """Serializer that includes the plaintext token (used only on creation)."""

    token = serializers.CharField(read_only=True)

    class Meta(ChannelSerializer.Meta):
        fields = [*ChannelSerializer.Meta.fields, "token"]
