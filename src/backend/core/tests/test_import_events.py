"""Tests for the ICS import events feature."""  # pylint: disable=too-many-lines

import json
from datetime import datetime
from datetime import timezone as dt_tz
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

import pytest
import requests as req
from rest_framework.test import APIClient

from core import factories
from core.services.caldav_service import CalDAVClient, CalendarService
from core.services.import_service import MAX_FILE_SIZE, ICSImportService, ImportResult

pytestmark = pytest.mark.django_db

# --- ICS test constants ---

ICS_SINGLE_EVENT = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:single-event-123
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Team meeting
DESCRIPTION:Weekly standup
END:VEVENT
END:VCALENDAR"""

ICS_MULTIPLE_EVENTS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260210T090000Z
DTEND:20260210T100000Z
SUMMARY:Morning standup
END:VEVENT
BEGIN:VEVENT
UID:event-2
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Afternoon review
END:VEVENT
BEGIN:VEVENT
UID:event-3
DTSTART:20260211T100000Z
DTEND:20260211T110000Z
SUMMARY:Planning session
END:VEVENT
END:VCALENDAR"""

ICS_ALL_DAY_EVENT = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:allday-event-1
DTSTART;VALUE=DATE:20260215
DTEND;VALUE=DATE:20260216
SUMMARY:Company holiday
END:VEVENT
END:VCALENDAR"""

ICS_WITH_TIMEZONE = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VTIMEZONE
TZID:Europe/Paris
BEGIN:STANDARD
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:tz-event-1
DTSTART;TZID=Europe/Paris:20260210T140000
DTEND;TZID=Europe/Paris:20260210T150000
SUMMARY:Paris meeting
END:VEVENT
END:VCALENDAR"""

ICS_RECURRING_EVENT = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:recurring-event-1
DTSTART:20260210T090000Z
DTEND:20260210T100000Z
SUMMARY:Daily standup
RRULE:FREQ=DAILY;COUNT=5
END:VEVENT
END:VCALENDAR"""

ICS_WITH_ATTENDEES = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:attendee-event-1
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Review meeting
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com
END:VEVENT
END:VCALENDAR"""

ICS_WITH_NEWLINES_IN_DESCRIPTION = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:newline-desc-1
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Meeting with notes
DESCRIPTION:Line one\\nLine two\\nLine three\\, with comma
END:VEVENT
END:VCALENDAR"""

ICS_EMPTY = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
END:VCALENDAR"""

ICS_INVALID = b"This is not valid ICS data"

ICS_VALARM_NO_ACTION = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:valarm-no-action-1
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Event with broken alarm
BEGIN:VALARM
TRIGGER:-PT15M
DESCRIPTION:Reminder
END:VALARM
END:VEVENT
END:VCALENDAR"""

ICS_RECURRING_WITH_EXCEPTION = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:recurring-exc-1
DTSTART:20260210T090000Z
DTEND:20260210T100000Z
SUMMARY:Weekly sync
RRULE:FREQ=WEEKLY;COUNT=4
END:VEVENT
BEGIN:VEVENT
UID:recurring-exc-1
RECURRENCE-ID:20260217T090000Z
DTSTART:20260217T100000Z
DTEND:20260217T110000Z
SUMMARY:Weekly sync (moved)
END:VEVENT
END:VCALENDAR"""

ICS_DEAD_RECURRING = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
DTSTART:20191024T170000Z
DTEND:20191024T180000Z
RRULE:FREQ=WEEKLY;UNTIL=20191106T225959Z;INTERVAL=2
EXDATE:20191024T170000Z
SUMMARY:Dead recurring event
UID:dead-recurring-1
END:VEVENT
END:VCALENDAR"""

ICS_WITH_BINARY_ATTACHMENT = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:attach-binary-1
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Event with inline attachment
ATTACH;VALUE=BINARY;ENCODING=BASE64;FMTTYPE=image/png:iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==
END:VEVENT
END:VCALENDAR"""

ICS_WITH_URL_ATTACHMENT = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:attach-url-1
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Event with URL attachment
ATTACH;FMTTYPE=application/pdf:https://example.com/doc.pdf
END:VEVENT
END:VCALENDAR"""

# Generate a large description (200KB) for truncation testing
_LARGE_DESC = "A" * 200000
ICS_WITH_LARGE_DESCRIPTION = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
    b"BEGIN:VEVENT\r\nUID:large-desc-1\r\n"
    b"DTSTART:20260210T140000Z\r\nDTEND:20260210T150000Z\r\n"
    b"SUMMARY:Event with huge description\r\nDESCRIPTION:"
    + _LARGE_DESC.encode()
    + b"\r\nEND:VEVENT\r\nEND:VCALENDAR"
)

# Generate an ICS that exceeds 1MB via many ATTENDEE lines (not stripped by sanitizer)
_OVERSIZED_ATTENDEES = "\r\n".join(
    f"ATTENDEE;CN=User {i}:mailto:user{i}@example-long-domain-padding-{i:06d}.com"
    for i in range(15000)
)
ICS_OVERSIZED_EVENT = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
    b"BEGIN:VEVENT\r\nUID:oversized-event-1\r\n"
    b"DTSTART:20260210T140000Z\r\nDTEND:20260210T150000Z\r\n"
    b"SUMMARY:Oversized event\r\n"
    + _OVERSIZED_ATTENDEES.encode()
    + b"\r\nEND:VEVENT\r\nEND:VCALENDAR"
)

ICS_NO_DTSTART = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:no-start-event
SUMMARY:Missing start
END:VEVENT
END:VCALENDAR"""


def _make_sabredav_response(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    status_code=200,
    total_events=0,
    imported_count=0,
    duplicate_count=0,
    skipped_count=0,
    errors=None,
):
    """Build a mock requests.Response mimicking SabreDAV import plugin."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    body = {
        "total_events": total_events,
        "imported_count": imported_count,
        "duplicate_count": duplicate_count,
        "skipped_count": skipped_count,
        "errors": errors or [],
    }
    mock_resp.json.return_value = body
    mock_resp.text = json.dumps(body)
    return mock_resp


class TestICSImportService:
    """Unit tests for ICSImportService with mocked HTTP call to SabreDAV."""

    @patch("core.services.import_service.requests.post")
    def test_import_single_event(self, mock_post):
        """Importing a single event should succeed."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_SINGLE_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert result.skipped_count == 0
        assert not result.errors
        mock_post.assert_called_once()

        # Verify the raw ICS was sent as-is
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["data"] == ICS_SINGLE_EVENT

    @patch("core.services.import_service.requests.post")
    def test_import_multiple_events(self, mock_post):
        """Importing multiple events should forward all to SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            total_events=3, imported_count=3
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_MULTIPLE_EVENTS)

        assert result.total_events == 3
        assert result.imported_count == 3
        assert result.skipped_count == 0
        assert not result.errors
        # Single HTTP call, not one per event
        mock_post.assert_called_once()

    @patch("core.services.import_service.requests.post")
    def test_import_empty_ics(self, mock_post):
        """Importing an ICS with no events should return zero counts."""
        mock_post.return_value = _make_sabredav_response(
            total_events=0, imported_count=0
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_EMPTY)

        assert result.total_events == 0
        assert result.imported_count == 0
        assert result.skipped_count == 0
        assert not result.errors

    @patch("core.services.import_service.requests.post")
    def test_import_invalid_ics(self, mock_post):
        """Importing invalid ICS data should return an error from SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            status_code=400,
        )
        mock_post.return_value.text = '{"error": "Failed to parse ICS file"}'

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_INVALID)

        assert result.imported_count == 0
        assert len(result.errors) >= 1

    @patch("core.services.import_service.requests.post")
    def test_import_with_timezone(self, mock_post):
        """Events with timezones should be forwarded to SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_WITH_TIMEZONE)

        assert result.total_events == 1
        assert result.imported_count == 1

        # Verify the raw ICS was sent as-is (timezone included)
        call_kwargs = mock_post.call_args
        assert b"VTIMEZONE" in call_kwargs.kwargs["data"]
        assert b"Europe/Paris" in call_kwargs.kwargs["data"]

    @patch("core.services.import_service.requests.post")
    def test_import_partial_failure(self, mock_post):
        """When some events fail, SabreDAV reports partial success."""
        mock_post.return_value = _make_sabredav_response(
            total_events=3,
            imported_count=2,
            skipped_count=1,
            errors=[
                {
                    "uid": "event-2",
                    "summary": "Afternoon review",
                    "error": "Some CalDAV error",
                }
            ],
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_MULTIPLE_EVENTS)

        assert result.total_events == 3
        assert result.imported_count == 2
        assert result.skipped_count == 1
        assert len(result.errors) == 1
        # Only event name is exposed, not raw error details
        assert result.errors[0] == "Afternoon review"

    @patch("core.services.import_service.requests.post")
    def test_import_all_day_event(self, mock_post):
        """All-day events should be forwarded to SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_ALL_DAY_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 1

    @patch("core.services.import_service.requests.post")
    def test_import_valarm_without_action(self, mock_post):
        """VALARM without ACTION is handled by SabreDAV plugin repair."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_VALARM_NO_ACTION)

        assert result.total_events == 1
        assert result.imported_count == 1

    @patch("core.services.import_service.requests.post")
    def test_import_recurring_with_exception(self, mock_post):
        """Recurring event + modified occurrence handled by SabreDAV splitter."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_RECURRING_WITH_EXCEPTION)

        # Two VEVENTs with same UID = one logical event
        assert result.total_events == 1
        assert result.imported_count == 1

    @patch("core.services.import_service.requests.post")
    def test_import_event_missing_dtstart(self, mock_post):
        """Events without DTSTART handling is delegated to SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1,
            imported_count=0,
            skipped_count=1,
            errors=[
                {
                    "uid": "no-start-event",
                    "summary": "Missing start",
                    "error": "DTSTART is required",
                }
            ],
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_NO_DTSTART)

        assert result.total_events == 1
        assert result.imported_count == 0
        assert result.skipped_count == 1
        assert result.errors[0] == "Missing start"

    @patch("core.services.import_service.requests.post")
    def test_import_passes_calendar_path(self, mock_post):
        """The import URL should include the calendar's caldav_path."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        service.import_events(user, calendar, ICS_SINGLE_EVENT)

        call_args = mock_post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert calendar.caldav_path in url
        assert "?import" in url

    @patch("core.services.import_service.requests.post")
    def test_import_sends_auth_headers(self, mock_post):
        """The import request must include all required auth headers."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        service.import_events(user, calendar, ICS_SINGLE_EVENT)

        call_kwargs = mock_post.call_args.kwargs
        headers = call_kwargs["headers"]
        assert headers["X-Api-Key"] == settings.CALDAV_OUTBOUND_API_KEY
        assert headers["X-Forwarded-User"] == user.email
        assert headers["X-Calendars-Import"] == settings.CALDAV_OUTBOUND_API_KEY
        assert headers["Content-Type"] == "text/calendar"

    @patch("core.services.import_service.requests.post")
    def test_import_duplicates_not_treated_as_errors(self, mock_post):
        """Duplicate events should be counted separately, not as errors."""
        mock_post.return_value = _make_sabredav_response(
            total_events=3,
            imported_count=1,
            duplicate_count=2,
            skipped_count=0,
            errors=[],
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_MULTIPLE_EVENTS)

        assert result.total_events == 3
        assert result.imported_count == 1
        assert result.duplicate_count == 2
        assert result.skipped_count == 0
        assert not result.errors

    @patch("core.services.import_service.requests.post")
    def test_import_network_failure(self, mock_post):
        """Network failures should return a graceful error."""
        mock_post.side_effect = req.ConnectionError("Connection refused")

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        service = ICSImportService()
        result = service.import_events(user, calendar, ICS_SINGLE_EVENT)

        assert result.imported_count == 0
        assert len(result.errors) >= 1


class TestImportEventsAPI:
    """API endpoint tests for the import_events action."""

    def _get_url(self, calendar_id):
        return f"/api/v1.0/calendars/{calendar_id}/import_events/"

    def test_import_events_requires_authentication(self):
        """Unauthenticated requests should be rejected."""
        calendar = factories.CalendarFactory()
        client = APIClient()

        response = client.post(self._get_url(calendar.id))

        assert response.status_code == 401

    def test_import_events_forbidden_for_non_owner(self):
        """Non-owners should not be able to access the calendar."""
        owner = factories.UserFactory()
        other_user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=owner)

        client = APIClient()
        client.force_login(other_user)

        ics_file = SimpleUploadedFile(
            "events.ics", ICS_SINGLE_EVENT, content_type="text/calendar"
        )
        response = client.post(
            self._get_url(calendar.id), {"file": ics_file}, format="multipart"
        )

        # Calendar not in queryset for non-owner, so 404 (not 403)
        assert response.status_code == 404

    def test_import_events_missing_file(self):
        """Request without a file should return 400."""
        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        client = APIClient()
        client.force_login(user)

        response = client.post(self._get_url(calendar.id), format="multipart")

        assert response.status_code == 400
        assert "No file provided" in response.json()["error"]

    def test_import_events_file_too_large(self):
        """Files exceeding MAX_FILE_SIZE should be rejected."""
        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        client = APIClient()
        client.force_login(user)

        large_file = SimpleUploadedFile(
            "events.ics",
            b"x" * (MAX_FILE_SIZE + 1),
            content_type="text/calendar",
        )
        response = client.post(
            self._get_url(calendar.id), {"file": large_file}, format="multipart"
        )

        assert response.status_code == 400
        assert "too large" in response.json()["error"]

    @patch.object(ICSImportService, "import_events")
    def test_import_events_success(self, mock_import):
        """Successful import should return result data."""
        mock_import.return_value = ImportResult(
            total_events=3,
            imported_count=3,
            duplicate_count=0,
            skipped_count=0,
            errors=[],
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        client = APIClient()
        client.force_login(user)

        ics_file = SimpleUploadedFile(
            "events.ics", ICS_MULTIPLE_EVENTS, content_type="text/calendar"
        )
        response = client.post(
            self._get_url(calendar.id), {"file": ics_file}, format="multipart"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_events"] == 3
        assert data["imported_count"] == 3
        assert data["skipped_count"] == 0
        assert "errors" not in data

    @patch.object(ICSImportService, "import_events")
    def test_import_events_partial_success(self, mock_import):
        """Partial success should include errors in response."""
        mock_import.return_value = ImportResult(
            total_events=3,
            imported_count=2,
            duplicate_count=0,
            skipped_count=1,
            errors=["Planning session"],
        )

        user = factories.UserFactory()
        calendar = factories.CalendarFactory(owner=user)

        client = APIClient()
        client.force_login(user)

        ics_file = SimpleUploadedFile(
            "events.ics", ICS_MULTIPLE_EVENTS, content_type="text/calendar"
        )
        response = client.post(
            self._get_url(calendar.id), {"file": ics_file}, format="multipart"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_events"] == 3
        assert data["imported_count"] == 2
        assert data["skipped_count"] == 1
        assert len(data["errors"]) == 1


@pytest.mark.skipif(
    not settings.CALDAV_URL,
    reason="CalDAV server URL not configured",
)
class TestImportEventsE2E:
    """End-to-end tests that import ICS events through the real SabreDAV server."""

    def _create_calendar(self, user):
        """Create a real calendar in both Django and SabreDAV."""
        service = CalendarService()
        return service.create_calendar(user, name="Import Test", color="#3174ad")

    def test_import_single_event_e2e(self):
        """Import a single event and verify it exists in SabreDAV."""
        user = factories.UserFactory(email="import-single@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, calendar, ICS_SINGLE_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert result.skipped_count == 0
        assert not result.errors

        # Verify the event actually exists in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            calendar.caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 11, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Team meeting"
        assert events[0]["uid"] == "single-event-123"

    def test_import_multiple_events_e2e(self):
        """Import multiple events and verify they all exist in SabreDAV."""
        user = factories.UserFactory(email="import-multi@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, calendar, ICS_MULTIPLE_EVENTS)

        assert result.total_events == 3
        assert result.imported_count == 3
        assert not result.errors

        # Verify all events exist in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            calendar.caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 12, tzinfo=dt_tz.utc),
        )
        assert len(events) == 3
        titles = {e["title"] for e in events}
        assert titles == {"Morning standup", "Afternoon review", "Planning session"}

    def test_import_all_day_event_e2e(self):
        """Import an all-day event and verify it exists in SabreDAV."""
        user = factories.UserFactory(email="import-allday@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, calendar, ICS_ALL_DAY_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify the event exists in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            calendar.caldav_path,
            start=datetime(2026, 2, 14, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 17, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Company holiday"

    def test_import_with_timezone_e2e(self):
        """Import an event with timezone info and verify it in SabreDAV."""
        user = factories.UserFactory(email="import-tz@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, calendar, ICS_WITH_TIMEZONE)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify the event exists in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            calendar.caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 11, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Paris meeting"

    def test_import_via_api_e2e(self):
        """Import events via the API endpoint hitting real SabreDAV."""
        user = factories.UserFactory(email="import-api@example.com")
        calendar = self._create_calendar(user)

        client = APIClient()
        client.force_login(user)

        ics_file = SimpleUploadedFile(
            "events.ics", ICS_MULTIPLE_EVENTS, content_type="text/calendar"
        )
        response = client.post(
            f"/api/v1.0/calendars/{calendar.id}/import_events/",
            {"file": ics_file},
            format="multipart",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_events"] == 3
        assert data["imported_count"] == 3
        assert data["skipped_count"] == 0

        # Verify events actually exist in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            calendar.caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 12, tzinfo=dt_tz.utc),
        )
        assert len(events) == 3

    def test_import_event_with_attendees_then_update_e2e(self):
        """Import an event with attendees and update it.

        This exercises the SabreDAV beforeWriteContent codepath in the
        AttendeeNormalizerPlugin, which previously failed because the
        plugin used the wrong callback signature for that event.
        """
        user = factories.UserFactory(email="import-attendee@example.com")
        calendar = self._create_calendar(user)

        # Import event with attendees
        import_service = ICSImportService()
        result = import_service.import_events(user, calendar, ICS_WITH_ATTENDEES)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Update the same event — triggers beforeWriteContent in SabreDAV
        caldav = CalDAVClient()
        caldav.update_event(
            user,
            calendar.caldav_path,
            "attendee-event-1",
            {"title": "Updated review meeting"},
        )

        # Verify update was applied
        events = caldav.get_events(
            user,
            calendar.caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 11, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Updated review meeting"

    def test_import_event_with_ics_escapes_e2e(self):
        """Import event whose description contains ICS escapes (\\n, \\,).

        These backslash sequences in ICS data can cause PostgreSQL bytea
        parse errors if the calendardata column is bytea and SabreDAV
        binds values as PARAM_STR instead of PARAM_LOB.
        """
        user = factories.UserFactory(email="import-escapes@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(
            user, calendar, ICS_WITH_NEWLINES_IN_DESCRIPTION
        )

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify event exists in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            calendar.caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 11, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Meeting with notes"

    def test_import_same_file_twice_no_duplicates_e2e(self):
        """Importing the same ICS file twice should not create duplicates."""
        user = factories.UserFactory(email="import-dedup@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()

        # First import
        result1 = import_service.import_events(user, calendar, ICS_MULTIPLE_EVENTS)
        assert result1.imported_count == 3
        assert not result1.errors

        # Second import of the same file — all should be duplicates
        result2 = import_service.import_events(user, calendar, ICS_MULTIPLE_EVENTS)
        assert result2.duplicate_count == 3
        assert result2.imported_count == 0
        assert result2.skipped_count == 0

        # Verify no duplicates in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            calendar.caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 12, tzinfo=dt_tz.utc),
        )
        assert len(events) == 3

    def test_import_dead_recurring_event_skipped_silently_e2e(self):
        """A recurring event whose EXDATE excludes all instances is skipped, not an error."""
        user = factories.UserFactory(email="import-dead-recur@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, calendar, ICS_DEAD_RECURRING)

        assert result.total_events == 1
        assert result.imported_count == 0
        assert result.skipped_count == 1
        assert not result.errors

    def _get_raw_event(self, user, calendar, uid):
        """Fetch the raw ICS data of a single event from SabreDAV by UID."""
        caldav_client = CalDAVClient()
        client = caldav_client._get_client(user)  # pylint: disable=protected-access
        cal_url = f"{caldav_client.base_url}{calendar.caldav_path}"
        cal = client.calendar(url=cal_url)
        event = cal.event_by_uid(uid)
        return event.data

    def test_import_strips_binary_attachments_e2e(self):
        """Binary attachments should be stripped during import."""
        user = factories.UserFactory(email="import-strip-attach@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(
            user, calendar, ICS_WITH_BINARY_ATTACHMENT
        )

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify event exists and binary attachment was stripped
        raw = self._get_raw_event(user, calendar, "attach-binary-1")
        assert "Event with inline attachment" in raw
        assert "iVBORw0KGgo" not in raw
        assert "ATTACH" not in raw

    def test_import_keeps_url_attachments_e2e(self):
        """URL-based attachments should NOT be stripped during import."""
        user = factories.UserFactory(email="import-keep-url-attach@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, calendar, ICS_WITH_URL_ATTACHMENT)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify URL attachment is preserved in raw ICS
        raw = self._get_raw_event(user, calendar, "attach-url-1")
        assert "https://example.com/doc.pdf" in raw
        assert "ATTACH" in raw

    def test_import_truncates_large_description_e2e(self):
        """Descriptions exceeding IMPORT_MAX_DESCRIPTION_BYTES should be truncated."""
        user = factories.UserFactory(email="import-trunc-desc@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(
            user, calendar, ICS_WITH_LARGE_DESCRIPTION
        )

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify description was truncated (default 100KB limit, original 200KB)
        raw = self._get_raw_event(user, calendar, "large-desc-1")
        assert "Event with huge description" in raw
        # Raw ICS should be much smaller than the 200KB original
        assert len(raw) < 150000
        # Should end with truncation marker
        assert "..." in raw


@pytest.mark.skipif(
    not settings.CALDAV_URL,
    reason="CalDAV server URL not configured",
)
class TestCalendarSanitizerE2E:
    """E2E tests for CalendarSanitizerPlugin on normal CalDAV PUT operations."""

    def _create_calendar(self, user):
        """Create a real calendar in both Django and SabreDAV."""
        service = CalendarService()
        return service.create_calendar(user, name="Sanitizer Test", color="#3174ad")

    def _get_raw_event(self, user, calendar, uid):
        """Fetch the raw ICS data of a single event from SabreDAV by UID."""
        caldav_client = CalDAVClient()
        client = caldav_client._get_client(user)  # pylint: disable=protected-access
        cal_url = f"{caldav_client.base_url}{calendar.caldav_path}"
        cal = client.calendar(url=cal_url)
        event = cal.event_by_uid(uid)
        return event.data

    def test_caldav_put_strips_binary_attachment_e2e(self):
        """A normal CalDAV PUT with binary attachment should be sanitized."""
        user = factories.UserFactory(email="sanitizer-put-attach@example.com")
        calendar = self._create_calendar(user)

        caldav = CalDAVClient()
        caldav.create_event_raw(
            user, calendar.caldav_path, ICS_WITH_BINARY_ATTACHMENT.decode()
        )

        raw = self._get_raw_event(user, calendar, "attach-binary-1")
        assert "Event with inline attachment" in raw
        assert "iVBORw0KGgo" not in raw
        assert "ATTACH" not in raw

    def test_caldav_put_keeps_url_attachment_e2e(self):
        """A normal CalDAV PUT with URL attachment should preserve it."""
        user = factories.UserFactory(email="sanitizer-put-url@example.com")
        calendar = self._create_calendar(user)

        caldav = CalDAVClient()
        caldav.create_event_raw(
            user, calendar.caldav_path, ICS_WITH_URL_ATTACHMENT.decode()
        )

        raw = self._get_raw_event(user, calendar, "attach-url-1")
        assert "https://example.com/doc.pdf" in raw
        assert "ATTACH" in raw

    def test_caldav_put_truncates_large_description_e2e(self):
        """A normal CalDAV PUT with oversized description should be truncated."""
        user = factories.UserFactory(email="sanitizer-put-desc@example.com")
        calendar = self._create_calendar(user)

        caldav = CalDAVClient()
        caldav.create_event_raw(
            user, calendar.caldav_path, ICS_WITH_LARGE_DESCRIPTION.decode()
        )

        raw = self._get_raw_event(user, calendar, "large-desc-1")
        assert "Event with huge description" in raw
        assert len(raw) < 150000
        assert "..." in raw

    def test_caldav_put_rejects_oversized_event_e2e(self):
        """A CalDAV PUT exceeding max-resource-size should be rejected (HTTP 507)."""
        user = factories.UserFactory(email="sanitizer-put-oversize@example.com")
        calendar = self._create_calendar(user)

        caldav = CalDAVClient()
        with pytest.raises(Exception) as exc_info:
            caldav.create_event_raw(
                user, calendar.caldav_path, ICS_OVERSIZED_EVENT.decode()
            )
        # SabreDAV returns 507 Insufficient Storage
        assert "507" in str(exc_info.value) or "Insufficient" in str(exc_info.value)

    def test_import_rejects_oversized_event_e2e(self):
        """Import of an event exceeding max-resource-size should skip it."""
        user = factories.UserFactory(email="sanitizer-import-oversize@example.com")
        calendar = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, calendar, ICS_OVERSIZED_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 0
        assert result.skipped_count == 1
