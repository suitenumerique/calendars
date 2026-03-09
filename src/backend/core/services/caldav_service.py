"""Services for CalDAV integration."""

import json
import logging
import re
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Optional
from urllib.parse import unquote
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

import icalendar
import requests

import caldav as caldav_lib
from caldav import DAVClient
from caldav.elements.cdav import CalendarDescription
from caldav.elements.dav import DisplayName
from caldav.elements.ical import CalendarColor
from caldav.lib.error import NotFoundError

logger = logging.getLogger(__name__)


class CalDAVHTTPClient:
    """Low-level HTTP client for CalDAV server communication.

    Centralizes header building, URL construction, API key validation,
    and HTTP requests. All higher-level CalDAV consumers delegate to this.
    """

    BASE_URI_PATH = "/caldav"
    DEFAULT_TIMEOUT = 30

    def __init__(self):
        self.base_url = settings.CALDAV_URL.rstrip("/")

    @staticmethod
    def get_api_key() -> str:
        """Return the outbound API key, raising ValueError if not configured."""
        key = settings.CALDAV_OUTBOUND_API_KEY
        if not key:
            raise ValueError("CALDAV_OUTBOUND_API_KEY is not configured")
        return key

    @classmethod
    def build_base_headers(cls, user) -> dict:
        """Build authentication headers for CalDAV requests.

        Args:
            user: Object with .email and .organization_id attributes.

        Raises:
            ValueError: If user.email is not set.
        """
        if not user.email:
            raise ValueError("User has no email address")
        headers = {
            "X-Api-Key": cls.get_api_key(),
            "X-Forwarded-User": user.email,
            "X-CalDAV-Organization": str(user.organization_id),
        }
        org = getattr(user, "organization", None)
        if org and hasattr(org, "effective_sharing_level"):
            headers["X-CalDAV-Sharing-Level"] = org.effective_sharing_level
        return headers

    def build_url(self, path: str, query: str = "") -> str:
        """Build a full CalDAV URL from a resource path.

        Handles paths with or without the /api/v1.0/caldav prefix.
        """
        # If the path already includes the base URI prefix, use it directly
        if path.startswith(self.BASE_URI_PATH):
            url = f"{self.base_url}{path}"
        else:
            clean_path = path.lstrip("/")
            url = f"{self.base_url}{self.BASE_URI_PATH}/{clean_path}"
        if query:
            url = f"{url}?{query}"
        return url

    def request(  # noqa: PLR0913  # pylint: disable=too-many-arguments
        self,
        method: str,
        user,
        path: str,
        *,
        query: str = "",
        data=None,
        extra_headers: dict | None = None,
        timeout: int | None = None,
        content_type: str | None = None,
    ) -> requests.Response:
        """Make an authenticated HTTP request to the CalDAV server."""
        headers = self.build_base_headers(user)
        if content_type:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)

        url = self.build_url(path, query)
        return requests.request(
            method=method,
            url=url,
            headers=headers,
            data=data,
            timeout=timeout or self.DEFAULT_TIMEOUT,
        )

    def get_dav_client(self, user) -> DAVClient:
        """Return a configured caldav.DAVClient for the given user.

        Args:
            user: Object with .email and .organization_id attributes.
        """
        headers = self.build_base_headers(user)
        caldav_url = f"{self.base_url}{self.BASE_URI_PATH}/"
        return DAVClient(
            url=caldav_url,
            username=None,
            password=None,
            timeout=self.DEFAULT_TIMEOUT,
            headers=headers,
        )

    def find_event_by_uid(
        self, user, uid: str
    ) -> tuple[str | None, str | None, str | None]:
        """Find an event by UID across all of the user's calendars.

        Returns (ical_data, href, etag) or (None, None, None).
        """
        client = self.get_dav_client(user)
        try:
            principal = client.principal()
            for cal in principal.calendars():
                try:
                    event = cal.object_by_uid(uid)
                    etag = getattr(event, "props", {}).get("{DAV:}getetag") or getattr(
                        event, "etag", None
                    )
                    return event.data, str(event.url.path), etag
                except caldav_lib.error.NotFoundError:
                    continue
            logger.warning(
                "Event UID %s not found in user %s calendars", uid, user.email
            )
            return None, None, None
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("CalDAV error looking up event %s", uid)
            return None, None, None

    def put_event(
        self, user, href: str, ical_data: str, etag: str | None = None
    ) -> bool:
        """PUT updated iCalendar data back to CalDAV. Returns True on success.

        If *etag* is provided, the request includes an If-Match header to
        prevent lost updates from concurrent modifications.
        """
        try:
            extra_headers = {}
            if etag:
                extra_headers["If-Match"] = etag
            response = self.request(
                "PUT",
                user,
                href,
                data=ical_data.encode("utf-8"),
                content_type="text/calendar; charset=utf-8",
                extra_headers=extra_headers or None,
            )
            if response.status_code in (200, 201, 204):
                return True
            if response.status_code == 412:
                logger.warning("CalDAV PUT conflict (ETag mismatch) for %s", href)
                return False
            logger.error(
                "CalDAV PUT failed: %s %s",
                response.status_code,
                response.text[:500],
            )
            return False
        except requests.exceptions.RequestException:
            logger.exception("CalDAV PUT error for %s", href)
            return False

    @staticmethod
    def update_attendee_partstat(
        ical_data: str, email: str, new_partstat: str
    ) -> str | None:
        """Update the PARTSTAT of an attendee in iCalendar data.

        Returns the modified iCalendar string, or None if attendee not found.
        """
        cal = icalendar.Calendar.from_ical(ical_data)
        updated = False

        target = f"mailto:{email.lower()}"
        for component in cal.walk("VEVENT"):
            for _name, attendee in component.property_items("ATTENDEE"):
                if str(attendee).lower().strip() == target:
                    attendee.params["PARTSTAT"] = icalendar.vText(new_partstat)
                    updated = True

        if not updated:
            return None

        return cal.to_ical().decode("utf-8")


class CalDAVClient:
    """
    Client for communicating with CalDAV server using the caldav library.
    """

    def __init__(self):
        self._http = CalDAVHTTPClient()
        self.base_url = self._http.base_url

    def _calendar_url(self, calendar_path: str) -> str:
        """Build a full URL for a calendar path, including the BASE_URI_PATH."""
        return f"{self.base_url}{CalDAVHTTPClient.BASE_URI_PATH}{calendar_path}"

    def _get_client(self, user) -> DAVClient:
        """
        Get a CalDAV client for the given user.

        The CalDAV server requires API key authentication via Authorization header
        and X-Forwarded-User header for user identification.
        Includes X-CalDAV-Organization when the user has an org.
        """
        return self._http.get_dav_client(user)

    def get_calendar_info(self, user, calendar_path: str) -> dict | None:
        """
        Get calendar information from CalDAV server.
        Returns dict with name, color, description or None if not found.
        """
        client = self._get_client(user)
        calendar_url = self._calendar_url(calendar_path)

        try:
            calendar = client.calendar(url=calendar_url)
            # Fetch properties
            props = calendar.get_properties(
                [DisplayName(), CalendarColor(), CalendarDescription()]
            )

            name = props.get(DisplayName.tag, "Calendar")
            color = props.get(CalendarColor.tag, settings.DEFAULT_CALENDAR_COLOR)
            description = props.get(CalendarDescription.tag, "")

            # Clean up color (CalDAV may return with alpha channel like #RRGGBBAA)
            if color and len(color) == 9 and color.startswith("#"):
                color = color[:7]

            logger.info("Got calendar info from CalDAV: name=%s, color=%s", name, color)
            return {
                "name": name,
                "color": color,
                "description": description,
            }
        except NotFoundError:
            logger.warning("Calendar not found at path: %s", calendar_path)
            return None
        except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.error("Failed to get calendar info from CalDAV: %s", str(e))
            return None

    def create_calendar(  # pylint: disable=too-many-arguments
        self,
        user,
        calendar_name: str = "",
        calendar_id: str = "",
        color: str = "",
        *,
        name: str = "",
    ) -> str:
        """
        Create a new calendar in CalDAV server for the given user.
        Returns the CalDAV server path for the calendar.
        """
        calendar_name = calendar_name or name
        if not calendar_id:
            calendar_id = str(uuid4())
        if not color:
            color = settings.DEFAULT_CALENDAR_COLOR
        client = self._get_client(user)
        principal = client.principal()

        try:
            # Pass cal_id so the library uses our UUID for the path.
            calendar = principal.make_calendar(name=calendar_name, cal_id=calendar_id)

            if color:
                calendar.set_properties([CalendarColor(color)])

            # Extract CalDAV-relative path from the calendar URL
            calendar_url = str(calendar.url)
            if calendar_url.startswith(self.base_url):
                path = calendar_url[len(self.base_url) :]
            else:
                path = f"/calendars/users/{user.email}/{calendar_id}/"

            base_prefix = CalDAVHTTPClient.BASE_URI_PATH
            if path.startswith(base_prefix):
                path = path[len(base_prefix) :]
                if not path.startswith("/"):
                    path = "/" + path

            path = unquote(path)

            logger.info(
                "Created calendar in CalDAV server: %s at %s",
                calendar_name,
                path,
            )
            return path
        except Exception as e:
            logger.error("Failed to create calendar in CalDAV server: %s", str(e))
            raise

    def get_events(
        self,
        user,
        calendar_path: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list:
        """
        Get events from a calendar within a time range.
        Returns list of event dictionaries with parsed data.
        """

        # Default to current month if no range specified
        if start is None:
            start = timezone.now().replace(day=1, hour=0, minute=0, second=0)
        if end is None:
            end = start + timedelta(days=31)

        client = self._get_client(user)

        # Get calendar by URL
        calendar_url = self._calendar_url(calendar_path)
        calendar = client.calendar(url=calendar_url)

        try:
            # Search for events in the date range
            # Convert datetime to date for search if needed
            start_date = start.date() if isinstance(start, datetime) else start
            end_date = end.date() if isinstance(end, datetime) else end

            events = calendar.search(
                event=True,
                start=start_date,
                end=end_date,
                expand=True,  # Expand recurring events
            )

            # Parse events into dictionaries
            parsed_events = []
            for event in events:
                event_data = self._parse_event(event)
                if event_data:
                    parsed_events.append(event_data)

            return parsed_events
        except NotFoundError:
            logger.warning("Calendar not found at path: %s", calendar_path)
            return []
        except Exception as e:
            logger.error("Failed to get events from CalDAV server: %s", str(e))
            raise

    def create_event_raw(self, user, calendar_path: str, ics_data: str) -> str:
        """
        Create an event in CalDAV server from raw ICS data.
        The ics_data should be a complete VCALENDAR string.
        Returns the event UID.
        """
        client = self._get_client(user)
        calendar_url = self._calendar_url(calendar_path)
        calendar = client.calendar(url=calendar_url)

        try:
            event = calendar.save_event(ics_data)
            event_uid = str(event.icalendar_component.get("uid", ""))
            logger.info("Created event in CalDAV server: %s", event_uid)
            return event_uid
        except Exception as e:
            logger.error("Failed to create event in CalDAV server: %s", str(e))
            raise

    def create_event(self, user, calendar_path: str, event_data: dict) -> str:
        """
        Create a new event in CalDAV server.
        Returns the event UID.
        """

        client = self._get_client(user)
        calendar_url = self._calendar_url(calendar_path)
        calendar = client.calendar(url=calendar_url)

        # Extract event data
        dtstart = event_data.get("start", timezone.now())
        dtend = event_data.get("end", dtstart + timedelta(hours=1))
        summary = event_data.get("title", "New Event")
        description = event_data.get("description", "")
        location = event_data.get("location", "")

        # Generate UID if not provided
        event_uid = event_data.get("uid", str(uuid4()))

        try:
            # Create event using caldav library
            event = calendar.save_event(
                dtstart=dtstart,
                dtend=dtend,
                uid=event_uid,
                summary=summary,
                description=description,
                location=location,
            )

            # Extract UID from created event
            # The caldav library returns an Event object
            if hasattr(event, "icalendar_component"):
                event_uid = str(event.icalendar_component.get("uid", event_uid))
            elif hasattr(event, "vobject_instance"):
                event_uid = event.vobject_instance.vevent.uid.value

            logger.info("Created event in CalDAV server: %s", event_uid)
            return event_uid
        except Exception as e:
            logger.error("Failed to create event in CalDAV server: %s", str(e))
            raise

    def update_event(
        self, user, calendar_path: str, event_uid: str, event_data: dict
    ) -> None:
        """Update an existing event in CalDAV server."""

        client = self._get_client(user)
        calendar_url = self._calendar_url(calendar_path)
        calendar = client.calendar(url=calendar_url)

        try:
            target_event = calendar.object_by_uid(event_uid)

            # Update event properties
            dtstart = event_data.get("start")
            dtend = event_data.get("end")
            summary = event_data.get("title")
            description = event_data.get("description")
            location = event_data.get("location")

            # Update using icalendar component
            component = target_event.icalendar_component

            if dtstart:
                component["dtstart"] = dtstart
            if dtend:
                component["dtend"] = dtend
            if summary:
                component["summary"] = summary
            if description is not None:
                component["description"] = description
            if location is not None:
                component["location"] = location

            # Save the updated event
            target_event.save()

            logger.info("Updated event in CalDAV server: %s", event_uid)
        except NotFoundError:
            raise ValueError(f"Event with UID {event_uid} not found") from None
        except Exception as e:
            logger.error("Failed to update event in CalDAV server: %s", str(e))
            raise

    def delete_event(self, user, calendar_path: str, event_uid: str) -> None:
        """Delete an event from CalDAV server."""

        client = self._get_client(user)
        calendar_url = self._calendar_url(calendar_path)
        calendar = client.calendar(url=calendar_url)

        try:
            target_event = calendar.object_by_uid(event_uid)
            target_event.delete()
            logger.info("Deleted event from CalDAV server: %s", event_uid)
        except NotFoundError:
            raise ValueError(f"Event with UID {event_uid} not found") from None
        except Exception as e:
            logger.error("Failed to delete event from CalDAV server: %s", str(e))
            raise

    def get_user_calendar_paths(self, user) -> list[str]:
        """Return a list of CalDAV-relative calendar paths for the user."""
        client = self._get_client(user)
        principal = client.principal()
        paths = []
        base = f"{self.base_url}{CalDAVHTTPClient.BASE_URI_PATH}"
        for cal in principal.calendars():
            url = str(cal.url)
            if url.startswith(base):
                paths.append(unquote(url[len(base) :]))
        return paths

    def create_default_calendar(self, user) -> str:
        """Create a default calendar for a user. Returns the caldav_path."""
        from core.services.translation_service import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            TranslationService,
        )

        calendar_id = str(uuid4())
        lang = TranslationService.resolve_language(email=user.email)
        calendar_name = TranslationService.t("calendar.list.defaultCalendarName", lang)
        return self.create_calendar(
            user, calendar_name, calendar_id, color=settings.DEFAULT_CALENDAR_COLOR
        )

    def _parse_event(self, event) -> Optional[dict]:
        """
        Parse a caldav Event object and return event data as dictionary.
        """
        try:
            component = event.icalendar_component

            event_data = {
                "uid": str(component.get("uid", "")),
                "title": str(component.get("summary", "")),
                "start": component.get("dtstart").dt
                if component.get("dtstart")
                else None,
                "end": component.get("dtend").dt if component.get("dtend") else None,
                "description": str(component.get("description", "")),
                "location": str(component.get("location", "")),
            }

            # Convert datetime to string format for consistency
            if event_data["start"]:
                if isinstance(event_data["start"], datetime):
                    utc_start = event_data["start"].astimezone(dt_timezone.utc)
                    event_data["start"] = utc_start.strftime("%Y%m%dT%H%M%SZ")
                elif isinstance(event_data["start"], date):
                    event_data["start"] = event_data["start"].strftime("%Y%m%d")

            if event_data["end"]:
                if isinstance(event_data["end"], datetime):
                    utc_end = event_data["end"].astimezone(dt_timezone.utc)
                    event_data["end"] = utc_end.strftime("%Y%m%dT%H%M%SZ")
                elif isinstance(event_data["end"], date):
                    event_data["end"] = event_data["end"].strftime("%Y%m%d")

            return event_data if event_data.get("uid") else None
        except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            logger.warning("Failed to parse event: %s", str(e))
            return None


# CalendarService is kept as an alias for backwards compatibility
# with tests and signals that reference it.
CalendarService = CalDAVClient


# ---------------------------------------------------------------------------
# CalDAV path utilities
# ---------------------------------------------------------------------------

# Pattern: /calendars/users/<email-or-encoded>/<calendar-id>/
# or /calendars/resources/<resource-id>/<calendar-id>/
CALDAV_PATH_PATTERN = re.compile(
    r"^/calendars/(users|resources)/[^/]+/[a-zA-Z0-9-]+/$",
)


def normalize_caldav_path(caldav_path):
    """Normalize CalDAV path to consistent format.

    Strips the CalDAV API prefix (e.g. /api/v1.0/caldav/) if present,
    so that paths like /api/v1.0/caldav/calendars/users/user@ex.com/uuid/
    become /calendars/users/user@ex.com/uuid/.
    """
    if not caldav_path.startswith("/"):
        caldav_path = "/" + caldav_path
    # Strip CalDAV API prefix — keep from /calendars/ onwards
    calendars_idx = caldav_path.find("/calendars/")
    if calendars_idx > 0:
        caldav_path = caldav_path[calendars_idx:]
    if not caldav_path.endswith("/"):
        caldav_path = caldav_path + "/"
    return caldav_path


def _resource_belongs_to_org(resource_id: str, org_id: str) -> bool:
    """Check whether a resource principal belongs to the given organization.

    Queries the CalDAV internal API. Returns False on any error (fail-closed).
    """
    api_key = settings.CALDAV_INTERNAL_API_KEY
    caldav_url = settings.CALDAV_URL
    if not api_key or not caldav_url:
        return False
    try:
        resp = requests.get(
            f"{caldav_url.rstrip('/')}/caldav/internal-api/resources/{resource_id}",
            headers={"X-Internal-Api-Key": api_key},
            timeout=10,
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        return data.get("org_id") == org_id
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to verify resource org for %s", resource_id)
        return False


def verify_caldav_access(user, caldav_path):
    """Verify that the user has access to the CalDAV calendar.

    Checks that:
    1. The path matches the expected pattern (prevents path injection)
    2. For user calendars: the user's email matches the email in the path
    3. For resource calendars: the user has an organization

    Note: Fine-grained org-to-resource authorization is enforced by SabreDAV
    itself (via X-CalDAV-Organization header). This check only gates access
    for Django-level features (subscription tokens, imports).
    """
    if not CALDAV_PATH_PATTERN.match(caldav_path):
        return False
    parts = caldav_path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "calendars":
        return False
    # User calendars: calendars/users/<email>/<calendar-id>
    if parts[1] == "users":
        if not user.email:
            return False
        path_email = unquote(parts[2])
        return path_email.lower() == user.email.lower()
    # Resource calendars: calendars/resources/<resource-id>/<calendar-id>
    # Org membership is required. Fine-grained org-to-resource authorization
    # is enforced by SabreDAV via the X-CalDAV-Organization header on every
    # proxied request. For subscription tokens / imports, callers should
    # additionally use _resource_belongs_to_org() to verify ownership.
    if parts[1] == "resources":
        return bool(getattr(user, "organization_id", None))
    return False


def validate_caldav_proxy_path(path):
    """Validate that a CalDAV proxy path is safe.

    Prevents path traversal attacks by rejecting paths with:
    - Directory traversal sequences (../)
    - Null bytes
    - Paths that don't start with expected prefixes

    URL-decodes the path first so that encoded payloads like
    ``%2e%2e`` or ``%00`` cannot bypass the checks.
    """
    if not path:
        return True  # Empty path is fine (root request)

    # Decode percent-encoded characters before validation
    path = unquote(path)

    # Block directory traversal
    if ".." in path:
        return False

    # Block null bytes
    if "\x00" in path:
        return False

    clean = path.lstrip("/")

    # Explicitly block internal-api/ paths — these must never be proxied.
    # The allowlist below already rejects them, but an explicit block makes
    # the intent clear and survives future allowlist additions.
    blocked_prefixes = ("internal-api/",)
    if clean and any(clean.startswith(prefix) for prefix in blocked_prefixes):
        return False

    # Path must start with a known CalDAV resource prefix
    allowed_prefixes = ("calendars/", "principals/", ".well-known/")
    if clean and not any(clean.startswith(prefix) for prefix in allowed_prefixes):
        return False

    return True


def cleanup_organization_caldav_data(org):
    """Clean up CalDAV data for all members of an organization.

    Deletes each member's CalDAV data via the SabreDAV internal API,
    then deletes the Django User objects so the PROTECT foreign key
    on User.organization doesn't block org deletion.

    Called from Organization.delete() — NOT a signal, because the
    PROTECT FK raises ProtectedError before pre_delete fires.
    """
    if not settings.CALDAV_INTERNAL_API_KEY:
        return

    http = CalDAVHTTPClient()
    members = list(org.members.all())

    for user in members:
        if not user.email:
            continue
        try:
            http.request(
                "POST",
                user,
                "internal-api/users/delete",
                data=json.dumps({"email": user.email}).encode("utf-8"),
                content_type="application/json",
                extra_headers={
                    "X-Internal-Api-Key": settings.CALDAV_INTERNAL_API_KEY,
                },
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Failed to clean up CalDAV data for user %s (org %s)",
                user.email,
                org.external_id,
            )

    # Delete all members so the PROTECT FK doesn't block org deletion.
    # CalDAV cleanup is best-effort; orphaned CalDAV data is acceptable.
    org.members.all().delete()
