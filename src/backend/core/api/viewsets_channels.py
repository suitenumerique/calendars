"""Channel API for managing integration tokens."""

import logging
import secrets

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import models
from core.api import serializers
from core.enums import ChannelScopeLevel
from core.services.caldav_service import verify_caldav_access
from core.services.channel_event_service import ChannelEventService

logger = logging.getLogger(__name__)


class ChannelViewSet(viewsets.GenericViewSet):
    """CRUD for integration channels.

    Endpoints:
        GET    /api/v1.0/channels/                       — list (filterable by ?type=)
        POST   /api/v1.0/channels/                       — create (returns token once)
        GET    /api/v1.0/channels/{id}/                   — retrieve
        PATCH  /api/v1.0/channels/{id}/                   — update scopes
        DELETE /api/v1.0/channels/{id}/                   — delete
        POST   /api/v1.0/channels/{id}/regenerate-token/  — regenerate token

    scope_level, caldav_path, type, user, and organization are immutable
    after creation. Scopes can be updated via PATCH.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = serializers.ChannelSerializer

    def get_queryset(self):
        return models.Channel.objects.filter(user=self.request.user).select_related(
            "organization", "user"
        )

    def list(self, request):
        """List channels created by the current user, optionally filtered by type."""
        queryset = self.get_queryset()
        channel_type = request.query_params.get("type")
        if channel_type:
            queryset = queryset.filter(type=channel_type)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request):
        """Create a new channel and return the token (once).

        For type="ical-feed", returns an existing channel if one already
        exists for the same user + caldav_path (get-or-create semantics).
        """
        create_serializer = serializers.ChannelCreateSerializer(data=request.data)
        create_serializer.is_valid(raise_exception=True)
        data = create_serializer.validated_data

        caldav_path = data.get("caldav_path", "")
        channel_type = data["type"]
        calendar_name = data.get("calendar_name", "")
        scope_level = data["scope_level"]
        scopes = data["scopes"]

        # Global channels cannot be created via the API
        if scope_level == ChannelScopeLevel.GLOBAL:
            return Response(
                {
                    "detail": (
                        "Global channels can only be created via Django admin or CLI."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if caldav_path:
            if not verify_caldav_access(request.user, caldav_path):
                return Response(
                    {"detail": ("You don't have access to this calendar.")},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # For ical-feed, return existing channel if one exists
        if channel_type == "ical-feed" and caldav_path:
            existing = (
                self.get_queryset()
                .filter(caldav_path=caldav_path, type="ical-feed")
                .first()
            )
            if existing:
                current_name = existing.settings.get("calendar_name", "")
                if calendar_name and current_name != calendar_name:
                    existing.settings["calendar_name"] = calendar_name
                    existing.name = calendar_name
                    existing.save(
                        update_fields=[
                            "settings",
                            "name",
                            "updated_at",
                        ]
                    )
                serializer = self.get_serializer(existing, context={"request": request})
                return Response(serializer.data, status=status.HTTP_200_OK)

        token = secrets.token_urlsafe(16)
        channel_settings = {"scopes": scopes}
        if calendar_name:
            channel_settings["calendar_name"] = calendar_name

        channel = models.Channel(
            name=(data.get("name") or calendar_name or caldav_path or "Channel"),
            type=channel_type,
            scope_level=scope_level,
            user=request.user,
            caldav_path=caldav_path,
            organization=request.user.organization,
            settings=channel_settings,
            encrypted_settings={"token": token},
        )
        channel.save()

        channel.token = token
        serializer = serializers.ChannelWithTokenSerializer(
            channel, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        """Retrieve a channel (without token)."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(channel, context={"request": request})
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        """Update mutable channel fields (name, is_active, scopes)."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        update_serializer = serializers.ChannelUpdateSerializer(data=request.data)
        update_serializer.is_valid(raise_exception=True)
        data = update_serializer.validated_data

        update_fields = ["updated_at"]
        if "name" in data:
            channel.name = data["name"]
            update_fields.append("name")
        if "is_active" in data:
            channel.is_active = data["is_active"]
            update_fields.append("is_active")
        if "scopes" in data:
            channel.scopes = data["scopes"]
            update_fields.append("settings")

        channel.save(update_fields=update_fields)

        serializer = self.get_serializer(channel, context={"request": request})
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """Delete a channel."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        channel.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="regenerate-token")
    def regenerate_token(self, request, pk=None):
        """Regenerate the token for an existing channel."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        token = secrets.token_urlsafe(16)
        channel.encrypted_settings = {
            **channel.encrypted_settings,
            "token": token,
        }
        channel.save(update_fields=["encrypted_settings", "updated_at"])

        channel.token = token
        serializer = serializers.ChannelWithTokenSerializer(
            channel, context={"request": request}
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get", "delete"], url_path="events")
    def events(self, request, pk=None):
        """List or delete events created by this channel."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        service = ChannelEventService()
        channel_id = str(channel.pk)

        if request.method == "DELETE":
            result = service.delete_events(request.user, channel_id)
            return Response(result)

        events = service.list_events(request.user, channel_id)
        return Response({"events": events})

    @action(detail=True, methods=["get"], url_path="events/count")
    def events_count(self, request, pk=None):
        """Count events created by this channel."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        service = ChannelEventService()
        count = service.count_events(request.user, str(channel.pk))
        return Response({"count": count})

    def _get_owned_channel(self, pk):
        """Get a channel owned by the current user, or None."""
        try:
            return self.get_queryset().get(pk=pk)
        except models.Channel.DoesNotExist:
            return None
