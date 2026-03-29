"""Service for querying and managing events by channel."""

import logging

import requests

from core.services.caldav_service import CalDAVHTTPClient

logger = logging.getLogger(__name__)


class ChannelEventService:
    """Query and manage calendar events associated with a channel.

    Uses the CalDAV internal API to query the calendarobjects table
    for events that were created/updated by a specific channel.
    """

    def __init__(self):
        self._http = CalDAVHTTPClient()

    def list_events(self, user, channel_id: str) -> list[dict]:
        """List events created by a channel.

        Returns a list of dicts with keys: uid, uri, calendarid,
        created_by, created_at, calendar_path.
        """
        try:
            response = self._http.internal_request(
                "GET",
                user,
                f"internal-api/channel-events/{channel_id}",
            )
        except (requests.RequestException, ValueError) as exc:
            logger.error("Failed to list channel events: %s", exc)
            return []

        if response.status_code != 200:
            logger.error(
                "Channel events list returned %s: %s",
                response.status_code,
                response.text[:500],
            )
            return []

        try:
            return response.json().get("events", [])
        except ValueError:
            logger.error("Invalid JSON from channel events list")
            return []

    def count_events(self, user, channel_id: str) -> int:
        """Count events created by a channel."""
        try:
            response = self._http.internal_request(
                "GET",
                user,
                f"internal-api/channel-events/{channel_id}/count",
            )
        except (requests.RequestException, ValueError) as exc:
            logger.error("Failed to count channel events: %s", exc)
            return 0

        if response.status_code != 200:
            return 0

        try:
            return response.json().get("count", 0)
        except ValueError:
            return 0

    def delete_events(self, user, channel_id: str) -> dict:
        """Delete all events created by a channel.

        First lists events via internal API, then deletes each via CalDAV
        DELETE so that scheduling side-effects (cancellation emails) fire.

        Returns dict with deleted_count and errors.
        """
        events = self.list_events(user, channel_id)
        deleted = 0
        errors = []

        for event in events:
            uid = event.get("uid")
            uri = event.get("uri")
            calendar_path = event.get("calendar_path")
            if not uid or not calendar_path or not uri:
                continue

            href = f"{calendar_path}{uri}"
            try:
                response = self._http.request(
                    "DELETE",
                    user,
                    href,
                )
                if response.status_code in (200, 204):
                    deleted += 1
                else:
                    errors.append(uid)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Failed to delete event %s", uid)
                errors.append(uid)

        return {"deleted_count": deleted, "errors": errors}
