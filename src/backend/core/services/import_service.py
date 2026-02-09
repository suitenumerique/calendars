"""Service for importing events from ICS files."""

import logging
from dataclasses import dataclass, field

from django.conf import settings

import requests

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
        self.base_url = settings.CALDAV_URL.rstrip("/")

    def import_events(self, user, caldav_path: str, ics_data: bytes) -> ImportResult:
        """Import events from ICS data into a calendar.

        Sends the raw ICS bytes to SabreDAV's ?import endpoint which
        handles all ICS parsing, splitting by UID, VALARM repair, and
        per-event insertion.

        Args:
            user: The authenticated user performing the import.
            caldav_path: CalDAV path of the calendar
                (e.g. /calendars/user@example.com/uuid/).
            ics_data: Raw ICS file content.
        """
        result = ImportResult()

        # Ensure caldav_path includes the base URI prefix that SabreDAV expects
        base_uri = "/api/v1.0/caldav/"
        if not caldav_path.startswith(base_uri):
            caldav_path = base_uri.rstrip("/") + caldav_path
        url = f"{self.base_url}{caldav_path}?import"

        outbound_api_key = settings.CALDAV_OUTBOUND_API_KEY
        if not outbound_api_key:
            result.errors.append("CALDAV_OUTBOUND_API_KEY is not configured")
            return result

        headers = {
            "Content-Type": "text/calendar",
            "X-Api-Key": outbound_api_key,
            "X-Forwarded-User": user.email,
            "X-Calendars-Import": outbound_api_key,
        }

        try:
            # Timeout scales with file size: 60s base + 30s per MB of ICS data.
            # 8000 events (~4MB) took ~70s in practice.
            timeout = 60 + int(len(ics_data) / 1024 / 1024) * 30
            response = requests.post(
                url, data=ics_data, headers=headers, timeout=timeout
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
