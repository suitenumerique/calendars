"""Channel API for managing integration tokens."""

# pylint: disable=broad-exception-caught,import-outside-toplevel,protected-access

import logging
import secrets
from xml.sax.saxutils import escape as xml_escape

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import models
from core.api import serializers
from core.services.caldav_service import CalDAVClient, verify_caldav_access
from core.services.channel_event_service import ChannelEventService
from core.services.url_validation import URLValidationError, fetch_ics

logger = logging.getLogger(__name__)

# Custom property namespace for subscription source
SUBSCRIPTION_SOURCE_PROP = "{http://lasuite.numerique.gouv.fr/ns/}subscription-source"


class _SubscriptionQuotaExceeded(Exception):
    """Marker exception raised inside the subscription-create transaction
    when the per-user quota is already reached, so the atomic block can
    roll back any intermediate state before the view returns a 400."""


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

        if channel_type == "ical-subscription":
            serializer = serializers.ChannelSubscriptionSerializer(queryset, many=True)
        else:
            serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request):
        """Create a new channel and return the token (once).

        For type="ical-feed", returns an existing channel if one already
        exists for the same user + caldav_path (get-or-create semantics).
        For type="ical-subscription", creates a SabreDAV calendar and
        enqueues an initial sync task.
        """
        # Dispatch to subscription-specific flow
        if request.data.get("type") == "ical-subscription":
            return self._create_subscription(request)

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

    def _create_subscription(self, request):  # noqa: PLR0912, PLR0915  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        """Create an ical-subscription channel with a SabreDAV calendar."""
        # Fast-path check: fail early on obviously-over-quota requests
        # so we don't waste a network fetch. The authoritative atomic
        # re-check happens later inside transaction.atomic() to prevent
        # concurrent POSTs from racing past this point.
        current_count = models.Channel.objects.filter(
            user=request.user, type="ical-subscription"
        ).count()
        if current_count >= settings.MAX_SUBSCRIPTIONS_PER_USER:
            return Response(
                {
                    "detail": (
                        f"Maximum number of subscriptions reached"
                        f" ({settings.MAX_SUBSCRIPTIONS_PER_USER})."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub_serializer = serializers.ChannelSubscriptionCreateSerializer(
            data=request.data
        )
        sub_serializer.is_valid(raise_exception=True)
        data = sub_serializer.validated_data

        source_url = data["source_url"]
        name = data["name"]

        # Test fetch to verify URL works
        try:
            _status_code, ics_data, etag, last_modified = fetch_ics(source_url)
        except URLValidationError as exc:
            return Response(
                {"source_url": [str(exc)]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not ics_data:
            return Response(
                {"source_url": ["URL did not return calendar data"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create SabreDAV calendar
        caldav_client = CalDAVClient()
        try:
            caldav_path = caldav_client.create_calendar(
                request.user, calendar_name=name
            )
        except Exception:
            logger.exception("Failed to create SabreDAV calendar for subscription")
            return Response(
                {"detail": "Failed to create calendar"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Set custom properties via PROPPATCH (subscription-source + color)
        color = data.get("color", "")
        try:
            http = caldav_client._http  # noqa: SLF001
            color_prop = ""
            if color:
                color_prop = (
                    f"<a:calendar-color xmlns:a="
                    f'"http://apple.com/ns/ical/">'
                    f"{xml_escape(color)}</a:calendar-color>"
                )
            proppatch_body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<d:propertyupdate xmlns:d="DAV:" '
                'xmlns:ls="http://lasuite.numerique.gouv.fr/ns/">'
                "<d:set><d:prop>"
                f"<ls:subscription-source>{xml_escape(source_url)}</ls:subscription-source>"
                f"{color_prop}"
                "</d:prop></d:set>"
                "</d:propertyupdate>"
            )
            http.request(
                "PROPPATCH",
                request.user,
                caldav_path,
                data=proppatch_body.encode("utf-8"),
                content_type="application/xml; charset=utf-8",
            )
        except Exception:
            logger.exception("Failed to set subscription-source property")
            # Non-fatal: the channel settings still track the source URL

        # Atomically enforce the per-user quota and persist the channel
        # so concurrent POSTs can't both pass the count check. The
        # select_for_update on the user row serializes subscription
        # creation per user.
        user_model = get_user_model()
        try:
            with transaction.atomic():
                user_locked = user_model.objects.select_for_update().get(
                    pk=request.user.pk
                )
                current_count = models.Channel.objects.filter(
                    user=user_locked, type="ical-subscription"
                ).count()
                if current_count >= settings.MAX_SUBSCRIPTIONS_PER_USER:
                    raise _SubscriptionQuotaExceeded()

                channel = models.Channel(
                    name=name,
                    type="ical-subscription",
                    user=request.user,
                    caldav_path=caldav_path,
                    organization=request.user.organization,
                    settings={
                        "source_url": source_url,
                        "sync_interval": settings.SUBSCRIPTION_SYNC_INTERVAL,
                        "last_sync_status": "pending",
                        "last_sync_error": "",
                        "error_count": 0,
                        "etag": "",
                        "last_modified": "",
                    },
                )
                channel.save()
        except _SubscriptionQuotaExceeded:
            try:
                caldav_client._http.request(  # noqa: SLF001
                    "DELETE", request.user, caldav_path
                )
            except Exception:
                logger.exception("Failed to clean up SabreDAV calendar %s", caldav_path)
            return Response(
                {
                    "detail": (
                        f"Maximum number of subscriptions reached"
                        f" ({settings.MAX_SUBSCRIPTIONS_PER_USER})."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.exception("Failed to save channel, cleaning up SabreDAV calendar")
            try:
                caldav_client._http.request(  # noqa: SLF001
                    "DELETE", request.user, caldav_path
                )
            except Exception:
                logger.exception("Failed to clean up SabreDAV calendar %s", caldav_path)
            raise

        # Sync events immediately using the ICS data we already fetched
        try:
            from core.services.subscription_sync_service import (  # noqa: PLC0415
                SubscriptionSyncService,
            )

            service = SubscriptionSyncService()
            sync_result = service.sync_events(
                request.user, caldav_path, ics_data, channel_id=str(channel.pk)
            )
            channel.settings["last_sync_at"] = timezone.now().isoformat()
            channel.settings["etag"] = etag
            channel.settings["last_modified"] = last_modified
            if sync_result.errors:
                channel.settings["last_sync_status"] = "error"
                channel.settings["last_sync_error"] = (
                    f"{len(sync_result.errors)} event error(s)"
                )
                channel.settings["error_count"] = 1
            else:
                channel.settings["last_sync_status"] = "ok"
                channel.settings["last_sync_error"] = ""
                channel.settings["error_count"] = 0
            channel.save(update_fields=["settings", "updated_at"])
        except Exception as exc:
            logger.exception("Initial sync failed for channel %s", channel.pk)
            channel.settings["last_sync_status"] = "error"
            channel.settings["last_sync_error"] = str(exc)[:500]
            channel.settings["error_count"] = 1
            channel.settings["last_sync_at"] = timezone.now().isoformat()
            channel.save(update_fields=["settings", "updated_at"])

        serializer = serializers.ChannelSubscriptionSerializer(channel)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):  # noqa: PLR0912, PLR0915  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        """Update a subscription channel (name and/or source_url)."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if channel.type != "ical-subscription":
            return Response(
                {"detail": "Only subscription channels can be updated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        update_serializer = serializers.ChannelSubscriptionUpdateSerializer(
            data=request.data
        )
        update_serializer.is_valid(raise_exception=True)
        data = update_serializer.validated_data

        if "name" in data:
            channel.name = data["name"]

        new_source_url = data.get("source_url")
        ics_data = None
        new_etag = ""
        new_last_modified = ""
        if new_source_url and new_source_url != channel.settings.get("source_url"):
            # Validate the new URL by fetching it (keep the data for immediate sync)
            try:
                _status_code, ics_data, new_etag, new_last_modified = fetch_ics(
                    new_source_url
                )
            except URLValidationError as exc:
                return Response(
                    {"source_url": [str(exc)]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            channel.settings["source_url"] = new_source_url
            channel.settings["etag"] = ""
            channel.settings["last_modified"] = ""
            channel.settings["error_count"] = 0
            channel.settings["last_sync_status"] = "pending"
            channel.settings["last_sync_error"] = ""

            # Purge existing events before syncing from new source
            try:
                from core.services.subscription_sync_service import (  # noqa: PLC0415
                    SubscriptionSyncService,
                )

                SubscriptionSyncService().purge_events(
                    request.user, channel.caldav_path
                )
            except Exception:
                logger.exception(
                    "Failed to purge events for channel %s on URL change",
                    channel.pk,
                )

            # Update WebDAV property
            try:
                http = CalDAVClient()._http  # noqa: SLF001
                proppatch_body = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<d:propertyupdate xmlns:d="DAV:" '
                    'xmlns:ls="http://lasuite.numerique.gouv.fr/ns/">'
                    "<d:set><d:prop>"
                    "<ls:subscription-source>"
                    f"{xml_escape(new_source_url)}"
                    "</ls:subscription-source>"
                    "</d:prop></d:set>"
                    "</d:propertyupdate>"
                )
                http.request(
                    "PROPPATCH",
                    request.user,
                    channel.caldav_path,
                    data=proppatch_body.encode("utf-8"),
                    content_type="application/xml; charset=utf-8",
                )
            except Exception:
                logger.exception("Failed to update subscription-source property")

            # Sync immediately using the ICS data we already fetched
            if ics_data:
                try:
                    from core.services.subscription_sync_service import (  # noqa: PLC0415
                        SubscriptionSyncService,
                    )

                    service = SubscriptionSyncService()
                    sync_result = service.sync_events(
                        request.user,
                        channel.caldav_path,
                        ics_data,
                        channel_id=str(channel.pk),
                    )
                    channel.settings["last_sync_at"] = timezone.now().isoformat()
                    channel.settings["etag"] = new_etag
                    channel.settings["last_modified"] = new_last_modified
                    if sync_result.errors:
                        channel.settings["last_sync_status"] = "error"
                        channel.settings["last_sync_error"] = (
                            f"{len(sync_result.errors)} event error(s)"
                        )
                        channel.settings["error_count"] = 1
                    else:
                        channel.settings["last_sync_status"] = "ok"
                        channel.settings["last_sync_error"] = ""
                        channel.settings["error_count"] = 0
                except Exception as exc:
                    logger.exception(
                        "Immediate sync failed after URL update for channel %s",
                        channel.pk,
                    )
                    channel.settings["last_sync_status"] = "error"
                    channel.settings["last_sync_error"] = str(exc)[:500]
                    channel.settings["error_count"] = 1
                    channel.settings["last_sync_at"] = timezone.now().isoformat()

        # Update CalDAV properties (displayname + color) via PROPPATCH
        new_color = data.get("color")
        new_name = data.get("name")
        if (new_color or new_name) and channel.caldav_path:
            props = ""
            if new_name:
                props += f"<d:displayname>{xml_escape(new_name)}</d:displayname>"
            if new_color:
                props += (
                    f'<a:calendar-color xmlns:a="http://apple.com/ns/ical/">'
                    f"{xml_escape(new_color)}</a:calendar-color>"
                )
            try:
                http = CalDAVClient()._http  # noqa: SLF001
                proppatch = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<d:propertyupdate xmlns:d="DAV:">'
                    f"<d:set><d:prop>{props}</d:prop></d:set>"
                    "</d:propertyupdate>"
                )
                http.request(
                    "PROPPATCH",
                    request.user,
                    channel.caldav_path,
                    data=proppatch.encode("utf-8"),
                    content_type="application/xml; charset=utf-8",
                )
            except Exception:
                logger.exception("Failed to update CalDAV calendar properties")

        channel.save(update_fields=["name", "settings", "updated_at"])

        serializer = serializers.ChannelSubscriptionSerializer(channel)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Retrieve a channel (without token)."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(channel, context={"request": request})
        return Response(serializer.data)

    def destroy(self, request, pk=None):
        """Delete a channel.

        For ical-subscription channels, also deletes the SabreDAV calendar.
        """
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Clean up SabreDAV calendar for subscriptions
        if channel.type == "ical-subscription" and channel.caldav_path:
            try:
                http = CalDAVClient()._http  # noqa: SLF001
                http.request("DELETE", request.user, channel.caldav_path)
            except Exception:
                logger.exception(
                    "Failed to delete SabreDAV calendar %s for subscription %s",
                    channel.caldav_path,
                    channel.pk,
                )
                # Continue with channel deletion anyway

        channel.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request, pk=None):
        """Reactivate a stopped subscription channel."""
        channel = self._get_owned_channel(pk)
        if channel is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if channel.type != "ical-subscription":
            return Response(
                {"detail": "Only subscription channels can be reactivated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        channel.is_active = True
        channel.settings["error_count"] = 0
        channel.settings["last_sync_status"] = "pending"
        channel.settings["last_sync_error"] = ""
        channel.save(update_fields=["is_active", "settings", "updated_at"])

        # Enqueue immediate sync
        try:
            from core.tasks import sync_one_subscription  # noqa: PLC0415

            sync_one_subscription.send(str(channel.pk))
        except Exception:
            logger.exception(
                "Failed to enqueue sync after reactivation for channel %s",
                channel.pk,
            )

        serializer = serializers.ChannelSubscriptionSerializer(channel)
        return Response(serializer.data)

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
