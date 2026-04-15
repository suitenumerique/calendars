"""Subscription API — thin REST proxy over SabreDAV's internal API.

Subscription state lives entirely in SabreDAV: a ``SUBSCRIPTION``
principal per unique source URL, one owner calendar, per-user shares via
``calendarinstances``, and sync state in ``propertystorage``. Django
does not persist any subscription model — this viewset only validates
user input, delegates to the internal API, and triggers background
syncs.
"""

# pylint: disable=broad-exception-caught,import-outside-toplevel

import logging

from django.conf import settings

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.services.caldav_service import CalDAVHTTPClient
from core.services.url_validation import URLValidationError, fetch_ics, normalize_url

logger = logging.getLogger(__name__)


class SubscriptionViewSet(viewsets.ViewSet):
    """Manage external ICS subscriptions for the current user.

    Endpoints:
        GET    /api/v1.0/subscriptions/                 — list user's subscriptions
        POST   /api/v1.0/subscriptions/                 — subscribe
        DELETE /api/v1.0/subscriptions/{sub_id}/        — unsubscribe
        POST   /api/v1.0/subscriptions/{sub_id}/reactivate/ — reset error count + sync
    """

    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Return the user's subscription shares."""
        http = CalDAVHTTPClient()
        try:
            resp = http.internal_request(
                "GET",
                request.user,
                f"internal-api/subscriptions/for-user/{request.user.email}",
            )
        except ValueError as exc:
            logger.exception("Internal API not configured")
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if resp.status_code != 200:
            logger.error(
                "for-user endpoint returned %s: %s", resp.status_code, resp.text
            )
            return Response(
                {"detail": "Failed to list subscriptions."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(resp.json().get("subscriptions", []))

    def create(self, request):  # noqa: PLR0911  # pylint: disable=too-many-return-statements,too-many-locals
        """Subscribe the current user to an ICS URL.

        Validates SSRF/HTTPS, verifies the URL returns valid ICS data,
        then creates (or finds) the shared subscription calendar and
        adds the user's share row. Triggers an immediate sync.
        """
        raw_url = request.data.get("source_url", "")
        if not raw_url:
            return Response(
                {"source_url": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            source_url = normalize_url(raw_url)
        except (ValueError, AttributeError):
            return Response(
                {"source_url": ["Invalid URL."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Test fetch to verify the URL works and is valid ICS. Also
        # warms up the cache for the immediate sync below.
        try:
            _status, ics_data, etag, last_modified = fetch_ics(source_url)
        except URLValidationError as exc:
            return Response(
                {"source_url": [str(exc)]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not ics_data:
            return Response(
                {"source_url": ["URL did not return calendar data."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Enforce per-user quota by counting the user's existing shares.
        http = CalDAVHTTPClient()
        try:
            list_resp = http.internal_request(
                "GET",
                request.user,
                f"internal-api/subscriptions/for-user/{request.user.email}",
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if list_resp.status_code == 200:
            current = list_resp.json().get("subscriptions", [])
            if len(current) >= settings.MAX_SUBSCRIPTIONS_PER_USER:
                return Response(
                    {
                        "detail": (
                            "Maximum number of subscriptions reached "
                            f"({settings.MAX_SUBSCRIPTIONS_PER_USER})."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Create the share (find-or-create the principal server-side).
        name = request.data.get("name") or source_url
        color = request.data.get("color", "")
        payload = {
            "user_email": request.user.email,
            "source_url": source_url,
            "display_name": name,
            "sync_interval": settings.SUBSCRIPTION_SYNC_INTERVAL,
        }
        if color:
            payload["color"] = color
        try:
            sub_resp = http.internal_request(
                "POST",
                request.user,
                "internal-api/subscriptions/subscribe/",
                json=payload,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if sub_resp.status_code != 200:
            logger.error(
                "subscribe endpoint returned %s: %s",
                sub_resp.status_code,
                sub_resp.text,
            )
            return Response(
                {"detail": "Failed to create subscription."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        sub_data = sub_resp.json()
        subscription_id = sub_data["subscription_id"]
        caldav_path = "/" + sub_data["caldav_path"]

        # Kick off immediate sync with the already-fetched ICS data. We
        # call the service synchronously so the user sees events on the
        # next page load without waiting for the scheduler cycle.
        try:
            from core.services.subscription_sync_service import (  # noqa: PLC0415
                SubscriptionSyncService,
            )

            service = SubscriptionSyncService()
            service.apply_initial_sync(
                request.user,
                subscription_id=subscription_id,
                caldav_path=caldav_path,
                ics_data=ics_data,
                etag=etag,
                last_modified=last_modified,
            )
        except Exception:
            logger.exception("Initial sync failed for %s", subscription_id)

        return Response(
            {
                "subscription_id": subscription_id,
                "source_url": source_url,
                "caldav_path": "/" + sub_data["user_caldav_path"],
                "display_name": name,
                "color": color or "#3788d8",
            },
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, pk=None):
        """Unsubscribe the current user from a subscription."""
        http = CalDAVHTTPClient()
        try:
            resp = http.internal_request(
                "POST",
                request.user,
                "internal-api/subscriptions/unsubscribe/",
                json={
                    "user_email": request.user.email,
                    "subscription_id": pk,
                },
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if resp.status_code != 200:
            logger.error(
                "unsubscribe endpoint returned %s: %s", resp.status_code, resp.text
            )
            return Response(
                {"detail": "Failed to unsubscribe."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        """Reset a stopped subscription's error counters and trigger a sync."""
        http = CalDAVHTTPClient()
        try:
            resp = http.internal_request(
                "POST",
                request.user,
                f"internal-api/subscriptions/{pk}/sync-result/",
                json={
                    "status": "pending",
                    "error_message": "",
                    "error_count": 0,
                },
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if resp.status_code == 404:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if resp.status_code != 200:
            logger.error(
                "reactivate sync-result returned %s: %s",
                resp.status_code,
                resp.text,
            )
            return Response(
                {"detail": "Failed to reactivate subscription."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Dispatch an immediate background sync.
        try:
            from core.tasks import sync_one_subscription  # noqa: PLC0415

            sync_one_subscription.send(pk)
        except Exception:
            logger.exception("Failed to dispatch sync for %s", pk)

        return Response({"reactivated": True})
