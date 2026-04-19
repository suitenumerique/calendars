"""Client serializers for the calendars core app."""

from django.conf import settings
from django.utils.text import slugify

from rest_framework import serializers
from timezone_field.rest_framework import TimeZoneSerializerField

from core import models
from core.entitlements import EntitlementsUnavailableError, get_user_entitlements
from core.enums import ChannelScope, ChannelScopeLevel
from core.models import uuid_to_urlsafe


class OrganizationSerializer(serializers.ModelSerializer):
    """Serialize organizations."""

    sharing_level = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Organization
        fields = ["id", "name", "sharing_level"]
        read_only_fields = ["id", "name", "sharing_level"]

    def get_sharing_level(self, org) -> str:
        """Return the effective sharing level (org override or server default)."""
        return org.effective_sharing_level


class UserLiteSerializer(serializers.ModelSerializer):
    """Serialize users with limited fields."""

    class Meta:
        model = models.User
        fields = ["id", "full_name"]
        read_only_fields = ["id", "full_name"]


class UserSerializer(serializers.ModelSerializer):
    """Serialize users."""

    email = serializers.SerializerMethodField(read_only=True)
    timezone = TimeZoneSerializerField(use_pytz=False)

    class Meta:
        model = models.User
        fields = [
            "id",
            "email",
            "full_name",
            "language",
            "timezone",
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

    scopes = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = models.Channel
        fields = [
            "id",
            "name",
            "type",
            "scope_level",
            "organization",
            "user",
            "caldav_path",
            "scopes",
            "is_active",
            "settings",
            "url",
            "last_used_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_scopes(self, obj):
        """Get scopes from settings."""
        return obj.scopes

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
    type = serializers.ChoiceField(
        choices=[("caldav", "caldav"), ("ical-feed", "ical-feed")]
    )
    scope_level = serializers.ChoiceField(
        choices=[(s, s) for s in ChannelScopeLevel],
    )
    caldav_path = serializers.CharField(max_length=512, required=False, default="")
    calendar_name = serializers.CharField(max_length=255, required=False, default="")
    scopes = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[(s, s) for s in ChannelScope],
        ),
    )

    def validate_caldav_path(self, value):
        """Normalize caldav_path if provided."""
        if value:
            if not value.endswith("/"):
                value = value + "/"
            if not value.startswith("/"):
                value = "/" + value
        return value

    def validate(self, attrs):
        """Cross-validate required fields.

        ``scope_level=calendar`` requires a ``caldav_path``. ``ical-feed``
        channels are read-only single-calendar subscriptions and can only
        be created with ``scope_level=calendar``.
        """
        sl = attrs["scope_level"]
        if attrs.get("type") == "ical-feed" and sl != ChannelScopeLevel.CALENDAR:
            raise serializers.ValidationError(
                {"scope_level": "ical-feed channels require scope_level='calendar'."}
            )
        if sl == ChannelScopeLevel.CALENDAR and not attrs.get("caldav_path"):
            raise serializers.ValidationError(
                {"caldav_path": "Required for scope_level='calendar'."}
            )
        return attrs


class ChannelWithTokenSerializer(ChannelSerializer):
    """Serializer that includes the plaintext token (used only on creation)."""

    token = serializers.CharField(read_only=True)
    password = serializers.SerializerMethodField()

    class Meta(ChannelSerializer.Meta):
        fields = [*ChannelSerializer.Meta.fields, "token", "password"]

    def get_password(self, obj) -> str:
        """Build the CalDAV password: base64url(channel_id) followed by token.

        The short_id is a fixed-length (22-char) base64url-encoded UUID so
        the concatenation can be parsed by slicing.
        """
        short_id = uuid_to_urlsafe(obj.pk)
        return f"{short_id}{obj.token}"


class ChannelUpdateSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Serializer for updating mutable channel fields."""

    name = serializers.CharField(max_length=255, required=False)
    is_active = serializers.BooleanField(required=False)
    scopes = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[(s, s) for s in ChannelScope],
        ),
        required=False,
    )
