"""Client serializers for the calendars core app."""

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from core import models
from core.entitlements import EntitlementsUnavailableError, get_user_entitlements


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

    class Meta:
        model = models.User
        fields = [
            "id",
            "email",
            "full_name",
            "language",
        ]
        read_only_fields = ["id", "email", "full_name"]


class UserMeSerializer(UserSerializer):
    """Serialize users for me endpoint."""

    can_access = serializers.SerializerMethodField(read_only=True)
    can_admin = serializers.SerializerMethodField(read_only=True)
    organization = OrganizationSerializer(read_only=True)

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
        """Get cached entitlements for the user."""
        cache_attr = "_entitlements_cache"
        if not hasattr(self, cache_attr):
            try:
                setattr(
                    self,
                    cache_attr,
                    get_user_entitlements(user.sub, user.email),
                )
            except EntitlementsUnavailableError:
                setattr(self, cache_attr, None)
        return getattr(self, cache_attr)

    def get_can_access(self, user) -> bool:
        """Check entitlements for the current user."""
        entitlements = self._get_entitlements(user)
        if entitlements is None:
            return False  # fail-closed
        return entitlements.get("can_access", True)

    def get_can_admin(self, user) -> bool:
        """Check admin entitlement for the current user."""
        entitlements = self._get_entitlements(user)
        if entitlements is None:
            return False  # fail-closed
        return entitlements.get("can_admin", False)


class CalendarSubscriptionTokenSerializer(serializers.ModelSerializer):
    """Serializer for CalendarSubscriptionToken model."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = models.CalendarSubscriptionToken
        fields = [
            "token",
            "url",
            "caldav_path",
            "calendar_name",
            "is_active",
            "last_accessed_at",
            "created_at",
        ]
        read_only_fields = [
            "token",
            "url",
            "caldav_path",
            "calendar_name",
            "is_active",
            "last_accessed_at",
            "created_at",
        ]

    def get_url(self, obj) -> str:
        """Build the full subscription URL, enforcing HTTPS in production."""
        request = self.context.get("request")
        if request:
            url = request.build_absolute_uri(f"/ical/{obj.token}.ics")
        else:
            # Fallback to APP_URL if no request context
            app_url = settings.APP_URL
            url = f"{app_url.rstrip('/')}/ical/{obj.token}.ics"

        # Force HTTPS in production to protect the token in transit
        if not settings.DEBUG and url.startswith("http://"):
            url = url.replace("http://", "https://", 1)

        return url


class CalendarSubscriptionTokenCreateSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Serializer for creating a CalendarSubscriptionToken."""

    caldav_path = serializers.CharField(max_length=512)
    calendar_name = serializers.CharField(max_length=255, required=False, default="")

    def validate_caldav_path(self, value):
        """Validate and normalize the caldav_path."""
        # Normalize path to always have trailing slash
        if not value.endswith("/"):
            value = value + "/"
        # Normalize path to always start with /
        if not value.startswith("/"):
            value = "/" + value
        return value
