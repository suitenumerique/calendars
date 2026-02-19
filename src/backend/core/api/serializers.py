"""Client serializers for the calendars core app."""

from django.conf import settings
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from rest_framework import exceptions, serializers

from core import models


class UserLiteSerializer(serializers.ModelSerializer):
    """Serialize users with limited fields."""

    class Meta:
        model = models.User
        fields = ["id", "full_name", "short_name"]
        read_only_fields = ["id", "full_name", "short_name"]


class BaseAccessSerializer(serializers.ModelSerializer):
    """Serialize template accesses."""

    abilities = serializers.SerializerMethodField(read_only=True)

    def update(self, instance, validated_data):
        """Make "user" field is readonly but only on update."""
        validated_data.pop("user", None)
        return super().update(instance, validated_data)

    def get_abilities(self, access) -> dict:
        """Return abilities of the logged-in user on the instance."""
        request = self.context.get("request")
        if request:
            return access.get_abilities(request.user)
        return {}

    def validate(self, attrs):
        """
        Check access rights specific to writing (create/update)
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        role = attrs.get("role")

        # Update
        if self.instance:
            can_set_role_to = self.instance.get_abilities(user)["set_role_to"]

            if role and role not in can_set_role_to:
                message = (
                    f"You are only allowed to set role to {', '.join(can_set_role_to)}"
                    if can_set_role_to
                    else "You are not allowed to set this role for this template."
                )
                raise exceptions.PermissionDenied(message)

        # Create
        else:
            try:
                resource_id = self.context["resource_id"]
            except KeyError as exc:
                raise exceptions.ValidationError(
                    "You must set a resource ID in kwargs to create a new access."
                ) from exc

            if not self.Meta.model.objects.filter(  # pylint: disable=no-member
                Q(user=user) | Q(team__in=user.teams),
                role__in=[models.RoleChoices.OWNER, models.RoleChoices.ADMIN],
                **{self.Meta.resource_field_name: resource_id},  # pylint: disable=no-member
            ).exists():
                raise exceptions.PermissionDenied(
                    "You are not allowed to manage accesses for this resource."
                )

            if (
                role == models.RoleChoices.OWNER
                and not self.Meta.model.objects.filter(  # pylint: disable=no-member
                    Q(user=user) | Q(team__in=user.teams),
                    role=models.RoleChoices.OWNER,
                    **{self.Meta.resource_field_name: resource_id},  # pylint: disable=no-member
                ).exists()
            ):
                raise exceptions.PermissionDenied(
                    "Only owners of a resource can assign other users as owners."
                )

        # pylint: disable=no-member
        attrs[f"{self.Meta.resource_field_name}_id"] = self.context["resource_id"]
        return attrs


class UserSerializer(serializers.ModelSerializer):
    """Serialize users."""

    class Meta:
        model = models.User
        fields = [
            "id",
            "email",
            "full_name",
            "short_name",
            "language",
        ]
        read_only_fields = ["id", "email", "full_name", "short_name"]


class UserMeSerializer(UserSerializer):
    """Serialize users for me endpoint."""

    class Meta:
        model = models.User
        fields = UserSerializer.Meta.fields
        read_only_fields = UserSerializer.Meta.read_only_fields


class CalendarCreateSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Serializer for creating a Calendar (CalDAV only, no Django model)."""

    name = serializers.CharField(max_length=255)
    color = serializers.CharField(max_length=7, required=False, default="")
    description = serializers.CharField(required=False, default="")


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
            app_url = getattr(settings, "APP_URL", "")
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
