"""Service for importing events from ICS files."""

import logging
from dataclasses import dataclass, field

from django.conf import settings

import requests

from core.services.caldav_service import CalDAVHTTPClient

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@dataclass
class ImportResult:
    """Result of an ICS import operation.

    errors contains event names (summaries) of failed events,
    at most 10 entries.
    """

    total_events: int = 0
    imported_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


class ICSImportService:
    """Service for importing events from ICS data into a CalDAV calendar.

    Sends the raw ICS file in a single POST to the SabreDAV ICS import
    plugin which handles splitting, validation/repair, and direct DB
    insertion.
    """

    def __init__(self):
        self._http = CalDAVHTTPClient()

    def import_events(
        self,
        user,
        caldav_path: str,
        ics_data: bytes,
        channel_id: str = "",
    ) -> ImportResult:
        """Import events from ICS data into a calendar.

        Sends the raw ICS bytes to the SabreDAV internal API import
        endpoint which handles all ICS parsing, splitting by UID,
        VALARM repair, and per-event insertion.

        Args:
            user: The authenticated user performing the import.
            caldav_path: CalDAV path of the calendar
                (e.g. /calendars/users/user@example.com/uuid/).
            ics_data: Raw ICS file content.
            channel_id: Optional channel UUID for audit tracking.
        """
        result = ImportResult()

        if not settings.CALDAV_INTERNAL_API_KEY:
            result.errors.append("CALDAV_INTERNAL_API_KEY is not configured")
            return result

        # Extract calendar URI from caldav_path
        # Path format: /calendars/users/<email>/<calendar-uri>/
        parts = caldav_path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "calendars" and parts[1] == "users":
            principal_user = parts[2]
            calendar_uri = parts[3]
        else:
            result.errors.append("Invalid calendar path")
            return result

        # import runs in a background task so we can wait a decent amount of time
        timeout = 1200  # 20 minutes
        extra_headers = {}
        if channel_id:
            extra_headers["X-CalDAV-Channel-Id"] = channel_id
        try:
            response = self._http.internal_request(
                "POST",
                user,
                f"internal-api/import/{principal_user}/{calendar_uri}",
                data=ics_data,
                content_type="text/calendar",
                extra_headers=extra_headers or None,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            logger.error("Failed to reach SabreDAV import endpoint: %s", exc)
            result.errors.append("Failed to reach CalDAV server")
            return result

        if response.status_code != 200:
            logger.error(
                "SabreDAV import returned %s: %s",
                response.status_code,
                response.text[:500],
            )
            result.errors.append("CalDAV server error")
            return result

        try:
            data = response.json()
        except ValueError:
            logger.error("Invalid JSON from SabreDAV import: %s", response.text[:500])
            result.errors.append("Invalid response from CalDAV server")
            return result

        result.total_events = data.get("total_events", 0)
        result.imported_count = data.get("imported_count", 0)
        result.duplicate_count = data.get("duplicate_count", 0)
        result.skipped_count = data.get("skipped_count", 0)

        # SabreDAV returns structured errors {uid, summary, error}.
        # Log full details server-side, expose only event names to the frontend.
        for err in data.get("errors", []):
            if isinstance(err, dict):
                logger.warning(
                    "Import failed for uid=%s summary=%s: %s",
                    err.get("uid", "?"),
                    err.get("summary", "?"),
                    err.get("error", "?"),
                )
                result.errors.append(
                    err.get("summary") or err.get("uid", "Unknown event")
                )
            else:
                result.errors.append(str(err))

        return result
