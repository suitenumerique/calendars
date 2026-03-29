"""Channel API for managing integration tokens."""

import logging
import secrets

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import models
from core.api import serializers
from core.services.caldav_service import verify_caldav_access
from core.services.channel_event_service import ChannelEventService

logger = logging.getLogger(__name__)


class ChannelViewSet(viewsets.GenericViewSet):
    """CRUD for integration channels.

    Endpoints:
        GET    /api/v1.0/channels/                       — list (filterable by ?type=)
        POST   /api/v1.0/channels/                       — create (returns token once)
        GET    /api/v1.0/channels/{id}/                   — retrieve
        DELETE /api/v1.0/channels/{id}/                   — delete
        POST   /api/v1.0/channels/{id}/regenerate-token/  — regenerate token
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
        channel_type = data.get("type", "caldav")
        calendar_name = data.get("calendar_name", "")

        # If a caldav_path is specified, verify the user has access
        if caldav_path and not verify_caldav_access(request.user, caldav_path):
            return Response(
                {"detail": "You don't have access to this calendar."},
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
                # Update calendar_name if provided and different
                current_name = existing.settings.get("calendar_name", "")
                if calendar_name and current_name != calendar_name:
                    existing.settings["calendar_name"] = calendar_name
                    existing.name = calendar_name
                    existing.save(update_fields=["settings", "name", "updated_at"])
                serializer = self.get_serializer(existing, context={"request": request})
                return Response(serializer.data, status=status.HTTP_200_OK)

        token = secrets.token_urlsafe(16)
        channel_settings = {"role": data.get("role", models.Channel.ROLE_READER)}
        if calendar_name:
            channel_settings["calendar_name"] = calendar_name

        channel = models.Channel(
            name=data.get("name") or calendar_name or caldav_path or "Channel",
            type=channel_type,
            user=request.user,
            caldav_path=caldav_path,
            organization=request.user.organization,
            settings=channel_settings,
            encrypted_settings={"token": token},
        )
        channel.save()

        # Attach plaintext token for the response (not persisted)
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

        # GET: list events
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
