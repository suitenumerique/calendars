"""Tests for the ICS import events feature."""  # pylint: disable=too-many-lines,no-member

import json
import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

import pytest
import requests as req
from rest_framework.test import APIClient

from core import factories
from core.services.caldav_service import (
    CalDAVClient,
    CalDAVHTTPClient,
    CalendarService,
)
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


def _make_caldav_path(user):
    """Build a caldav_path string for a user (test helper)."""
    return f"/calendars/users/{user.email}/{uuid.uuid4()}/"


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

    @patch("core.services.caldav_service.requests.request")
    def test_import_single_event(self, mock_post):
        """Importing a single event should succeed."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_SINGLE_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert result.skipped_count == 0
        assert not result.errors
        mock_post.assert_called_once()

        # Verify the raw ICS was sent as-is
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["data"] == ICS_SINGLE_EVENT

    @patch("core.services.caldav_service.requests.request")
    def test_import_multiple_events(self, mock_post):
        """Importing multiple events should forward all to SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            total_events=3, imported_count=3
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_MULTIPLE_EVENTS)

        assert result.total_events == 3
        assert result.imported_count == 3
        assert result.skipped_count == 0
        assert not result.errors
        # Single HTTP call, not one per event
        mock_post.assert_called_once()

    @patch("core.services.caldav_service.requests.request")
    def test_import_empty_ics(self, mock_post):
        """Importing an ICS with no events should return zero counts."""
        mock_post.return_value = _make_sabredav_response(
            total_events=0, imported_count=0
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_EMPTY)

        assert result.total_events == 0
        assert result.imported_count == 0
        assert result.skipped_count == 0
        assert not result.errors

    @patch("core.services.caldav_service.requests.request")
    def test_import_invalid_ics(self, mock_post):
        """Importing invalid ICS data should return an error from SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            status_code=400,
        )
        mock_post.return_value.text = '{"error": "Failed to parse ICS file"}'

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_INVALID)

        assert result.imported_count == 0
        assert len(result.errors) >= 1

    @patch("core.services.caldav_service.requests.request")
    def test_import_with_timezone(self, mock_post):
        """Events with timezones should be forwarded to SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_WITH_TIMEZONE)

        assert result.total_events == 1
        assert result.imported_count == 1

        # Verify the raw ICS was sent as-is (timezone included)
        call_kwargs = mock_post.call_args
        assert b"VTIMEZONE" in call_kwargs.kwargs["data"]
        assert b"Europe/Paris" in call_kwargs.kwargs["data"]

    @patch("core.services.caldav_service.requests.request")
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
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_MULTIPLE_EVENTS)

        assert result.total_events == 3
        assert result.imported_count == 2
        assert result.skipped_count == 1
        assert len(result.errors) == 1
        # Only event name is exposed, not raw error details
        assert result.errors[0] == "Afternoon review"

    @patch("core.services.caldav_service.requests.request")
    def test_import_all_day_event(self, mock_post):
        """All-day events should be forwarded to SabreDAV."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_ALL_DAY_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 1

    @patch("core.services.caldav_service.requests.request")
    def test_import_valarm_without_action(self, mock_post):
        """VALARM without ACTION is handled by SabreDAV plugin repair."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_VALARM_NO_ACTION)

        assert result.total_events == 1
        assert result.imported_count == 1

    @patch("core.services.caldav_service.requests.request")
    def test_import_recurring_with_exception(self, mock_post):
        """Recurring event + modified occurrence handled by SabreDAV splitter."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_RECURRING_WITH_EXCEPTION)

        # Two VEVENTs with same UID = one logical event
        assert result.total_events == 1
        assert result.imported_count == 1

    @patch("core.services.caldav_service.requests.request")
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
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_NO_DTSTART)

        assert result.total_events == 1
        assert result.imported_count == 0
        assert result.skipped_count == 1
        assert result.errors[0] == "Missing start"

    @patch("core.services.caldav_service.requests.request")
    def test_import_passes_calendar_path(self, mock_post):
        """The import URL should use the internal-api/import/ endpoint."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        service.import_events(user, caldav_path, ICS_SINGLE_EVENT)

        call_args = mock_post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "internal-api/import/" in url
        # URL should contain the user email and calendar URI from the path
        parts = caldav_path.strip("/").split("/")
        assert parts[2] in url  # user email
        assert parts[3] in url  # calendar URI

    @patch("core.services.caldav_service.requests.request")
    def test_import_sends_auth_headers(self, mock_post):
        """The import request must include all required auth headers."""
        mock_post.return_value = _make_sabredav_response(
            total_events=1, imported_count=1
        )

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        service.import_events(user, caldav_path, ICS_SINGLE_EVENT)

        call_kwargs = mock_post.call_args.kwargs
        headers = call_kwargs["headers"]
        assert headers["X-LS-Api-Key"] == settings.CALDAV_OUTBOUND_API_KEY
        assert headers["X-LS-User"] == user.email
        assert headers["X-LS-Internal-Api-Key"] == settings.CALDAV_INTERNAL_API_KEY
        assert headers["Content-Type"] == "text/calendar"

    @patch("core.services.caldav_service.requests.request")
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
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_MULTIPLE_EVENTS)

        assert result.total_events == 3
        assert result.imported_count == 1
        assert result.duplicate_count == 2
        assert result.skipped_count == 0
        assert not result.errors

    @patch("core.services.caldav_service.requests.request")
    def test_import_network_failure(self, mock_post):
        """Network failures should return a graceful error."""
        mock_post.side_effect = req.ConnectionError("Connection refused")

        user = factories.UserFactory()
        caldav_path = _make_caldav_path(user)

        service = ICSImportService()
        result = service.import_events(user, caldav_path, ICS_SINGLE_EVENT)

        assert result.imported_count == 0
        assert len(result.errors) >= 1


class TestImportEventsAPI:
    """API endpoint tests for the import_events action."""

    IMPORT_URL = "/api/v1.0/calendars/import-events/"

    def test_import_events_requires_authentication(self):
        """Unauthenticated requests should be rejected."""
        client = APIClient()
        response = client.post(self.IMPORT_URL)
        assert response.status_code == 401

    def test_import_events_forbidden_for_wrong_user(self):
        """Users cannot import to a calendar they don't own."""
        owner = factories.UserFactory(email="owner@example.com")
        other_user = factories.UserFactory(email="other@example.com")
        caldav_path = f"/calendars/users/{owner.email}/some-uuid/"

        client = APIClient()
        client.force_login(other_user)

        ics_file = SimpleUploadedFile(
            "events.ics", ICS_SINGLE_EVENT, content_type="text/calendar"
        )
        response = client.post(
            self.IMPORT_URL,
            {"file": ics_file, "caldav_path": caldav_path},
            format="multipart",
        )
        assert response.status_code == 403

    def test_import_events_missing_caldav_path(self):
        """Request without caldav_path should return 400."""
        user = factories.UserFactory()
        client = APIClient()
        client.force_login(user)

        ics_file = SimpleUploadedFile(
            "events.ics", ICS_SINGLE_EVENT, content_type="text/calendar"
        )
        response = client.post(self.IMPORT_URL, {"file": ics_file}, format="multipart")
        assert response.status_code == 400
        assert "caldav_path" in response.json()["detail"]

    def test_import_events_missing_file(self):
        """Request without a file should return 400."""
        user = factories.UserFactory(email="nofile@example.com")
        caldav_path = f"/calendars/users/{user.email}/some-uuid/"

        client = APIClient()
        client.force_login(user)

        response = client.post(
            self.IMPORT_URL,
            {"caldav_path": caldav_path},
            format="multipart",
        )
        assert response.status_code == 400
        assert "No file provided" in response.json()["detail"]

    def test_import_events_file_too_large(self):
        """Files exceeding MAX_FILE_SIZE should be rejected."""
        user = factories.UserFactory(email="largefile@example.com")
        caldav_path = f"/calendars/users/{user.email}/some-uuid/"

        client = APIClient()
        client.force_login(user)

        large_file = SimpleUploadedFile(
            "events.ics",
            b"x" * (MAX_FILE_SIZE + 1),
            content_type="text/calendar",
        )
        response = client.post(
            self.IMPORT_URL,
            {"file": large_file, "caldav_path": caldav_path},
            format="multipart",
        )
        assert response.status_code == 400
        assert "too large" in response.json()["detail"]

    @patch.object(ICSImportService, "import_events")
    def test_import_events_returns_task_id(self, mock_import):
        """Successful import should return a task_id for polling."""
        mock_import.return_value = ImportResult(
            total_events=3,
            imported_count=3,
            duplicate_count=0,
            skipped_count=0,
            errors=[],
        )

        user = factories.UserFactory(email="success@example.com")
        caldav_path = f"/calendars/users/{user.email}/some-uuid/"

        client = APIClient()
        client.force_login(user)

        ics_file = SimpleUploadedFile(
            "events.ics", ICS_MULTIPLE_EVENTS, content_type="text/calendar"
        )
        response = client.post(
            self.IMPORT_URL,
            {"file": ics_file, "caldav_path": caldav_path},
            format="multipart",
        )

        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data

        # With EagerBroker, the task runs synchronously — poll for result
        task_response = client.get(f"/api/v1.0/tasks/{data['task_id']}/")
        assert task_response.status_code == 200
        task_data = task_response.json()
        assert task_data["status"] == "SUCCESS"
        assert task_data["result"]["total_events"] == 3
        assert task_data["result"]["imported_count"] == 3


@pytest.mark.xdist_group("caldav")
class TestImportEventsE2E:
    """End-to-end tests that import ICS events through the real SabreDAV server."""

    def _create_calendar(self, user):
        """Create a real calendar in SabreDAV. Returns the caldav_path."""
        service = CalendarService()
        return service.create_calendar(user, name="Import Test", color="#3174ad")

    def test_import_single_event_e2e(self):
        """Import a single event and verify it exists in SabreDAV."""
        user = factories.UserFactory(email="import-single@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, caldav_path, ICS_SINGLE_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert result.skipped_count == 0
        assert not result.errors

        # Verify the event actually exists in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 11, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Team meeting"
        assert events[0]["uid"] == "single-event-123"

    def test_import_multiple_events_e2e(self):
        """Import multiple events and verify they all exist in SabreDAV."""
        user = factories.UserFactory(email="import-multi@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, caldav_path, ICS_MULTIPLE_EVENTS)

        assert result.total_events == 3
        assert result.imported_count == 3
        assert not result.errors

        # Verify all events exist in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 12, tzinfo=dt_tz.utc),
        )
        assert len(events) == 3
        titles = {e["title"] for e in events}
        assert titles == {"Morning standup", "Afternoon review", "Planning session"}

    def test_import_all_day_event_e2e(self):
        """Import an all-day event and verify it exists in SabreDAV."""
        user = factories.UserFactory(email="import-allday@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, caldav_path, ICS_ALL_DAY_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify the event exists in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            caldav_path,
            start=datetime(2026, 2, 14, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 17, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Company holiday"

    def test_import_with_timezone_e2e(self):
        """Import an event with timezone info and verify it in SabreDAV."""
        user = factories.UserFactory(email="import-tz@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, caldav_path, ICS_WITH_TIMEZONE)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify the event exists in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 11, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Paris meeting"

    def test_import_via_api_e2e(self):
        """Import events via the API endpoint hitting real SabreDAV."""
        user = factories.UserFactory(email="import-api@example.com")
        caldav_path = self._create_calendar(user)

        client = APIClient()
        client.force_login(user)

        ics_file = SimpleUploadedFile(
            "events.ics", ICS_MULTIPLE_EVENTS, content_type="text/calendar"
        )
        response = client.post(
            "/api/v1.0/calendars/import-events/",
            {"file": ics_file, "caldav_path": caldav_path},
            format="multipart",
        )

        assert response.status_code == 202
        task_id = response.json()["task_id"]

        # With EagerBroker, poll for the synchronous result
        task_response = client.get(f"/api/v1.0/tasks/{task_id}/")
        assert task_response.status_code == 200
        data = task_response.json()
        assert data["status"] == "SUCCESS"
        assert data["result"]["total_events"] == 3
        assert data["result"]["imported_count"] == 3

        # Verify events actually exist in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            caldav_path,
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
        caldav_path = self._create_calendar(user)

        # Import event with attendees
        import_service = ICSImportService()
        result = import_service.import_events(user, caldav_path, ICS_WITH_ATTENDEES)

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Update the same event — triggers beforeWriteContent in SabreDAV
        caldav = CalDAVClient()
        caldav.update_event(
            user,
            caldav_path,
            "attendee-event-1",
            {"title": "Updated review meeting"},
        )

        # Verify update was applied
        events = caldav.get_events(
            user,
            caldav_path,
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
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(
            user, caldav_path, ICS_WITH_NEWLINES_IN_DESCRIPTION
        )

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify event exists in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 11, tzinfo=dt_tz.utc),
        )
        assert len(events) == 1
        assert events[0]["title"] == "Meeting with notes"

    def test_import_same_file_twice_no_duplicates_e2e(self):
        """Importing the same ICS file twice should not create duplicates."""
        user = factories.UserFactory(email="import-dedup@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()

        # First import
        result1 = import_service.import_events(user, caldav_path, ICS_MULTIPLE_EVENTS)
        assert result1.imported_count == 3
        assert not result1.errors

        # Second import of the same file — all should be duplicates
        result2 = import_service.import_events(user, caldav_path, ICS_MULTIPLE_EVENTS)
        assert result2.duplicate_count == 3
        assert result2.imported_count == 0
        assert result2.skipped_count == 0

        # Verify no duplicates in SabreDAV
        caldav = CalDAVClient()
        events = caldav.get_events(
            user,
            caldav_path,
            start=datetime(2026, 2, 10, tzinfo=dt_tz.utc),
            end=datetime(2026, 2, 12, tzinfo=dt_tz.utc),
        )
        assert len(events) == 3

    def test_import_dead_recurring_event_skipped_silently_e2e(self):
        """A recurring event whose EXDATE excludes all instances is skipped, not an error."""
        user = factories.UserFactory(email="import-dead-recur@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, caldav_path, ICS_DEAD_RECURRING)

        assert result.total_events == 1
        assert result.imported_count == 0
        assert result.skipped_count == 1
        assert not result.errors

    def _get_raw_event(self, user, caldav_path, uid):
        """Fetch the raw ICS data of a single event from SabreDAV by UID."""
        caldav_client = CalDAVClient()
        client = caldav_client._get_client(user)  # pylint: disable=protected-access
        cal_url = caldav_client._calendar_url(caldav_path)  # pylint: disable=protected-access
        cal = client.calendar(url=cal_url)
        event = cal.event_by_uid(uid)
        return event.data

    def test_import_strips_binary_attachments_e2e(self):
        """Binary attachments should be stripped during import."""
        user = factories.UserFactory(email="import-strip-attach@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(
            user, caldav_path, ICS_WITH_BINARY_ATTACHMENT
        )

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify event exists and binary attachment was stripped
        raw = self._get_raw_event(user, caldav_path, "attach-binary-1")
        assert "Event with inline attachment" in raw
        assert "iVBORw0KGgo" not in raw
        assert "ATTACH" not in raw

    def test_import_keeps_url_attachments_e2e(self):
        """URL-based attachments should NOT be stripped during import."""
        user = factories.UserFactory(email="import-keep-url-attach@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(
            user, caldav_path, ICS_WITH_URL_ATTACHMENT
        )

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify URL attachment is preserved in raw ICS
        raw = self._get_raw_event(user, caldav_path, "attach-url-1")
        assert "https://example.com/doc.pdf" in raw
        assert "ATTACH" in raw

    def test_import_truncates_large_description_e2e(self):
        """Descriptions exceeding IMPORT_MAX_DESCRIPTION_BYTES should be truncated."""
        user = factories.UserFactory(email="import-trunc-desc@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(
            user, caldav_path, ICS_WITH_LARGE_DESCRIPTION
        )

        assert result.total_events == 1
        assert result.imported_count == 1
        assert not result.errors

        # Verify description was truncated (default 100KB limit, original 200KB)
        raw = self._get_raw_event(user, caldav_path, "large-desc-1")
        assert "Event with huge description" in raw
        # Raw ICS should be much smaller than the 200KB original
        assert len(raw) < 150000
        # Should end with truncation marker
        assert "..." in raw


@pytest.mark.xdist_group("caldav")
class TestCalendarSanitizerE2E:
    """E2E tests for CalendarSanitizerPlugin on normal CalDAV PUT operations."""

    def _create_calendar(self, user):
        """Create a real calendar in SabreDAV. Returns the caldav_path."""
        service = CalendarService()
        return service.create_calendar(user, name="Sanitizer Test", color="#3174ad")

    def _get_raw_event(self, user, caldav_path, uid):
        """Fetch the raw ICS data of a single event from SabreDAV by UID."""
        caldav_client = CalDAVClient()
        client = caldav_client._get_client(user)  # pylint: disable=protected-access
        cal_url = caldav_client._calendar_url(caldav_path)  # pylint: disable=protected-access
        cal = client.calendar(url=cal_url)
        event = cal.event_by_uid(uid)
        return event.data

    def test_caldav_put_strips_binary_attachment_e2e(self):
        """A normal CalDAV PUT with binary attachment should be sanitized."""
        user = factories.UserFactory(email="sanitizer-put-attach@example.com")
        caldav_path = self._create_calendar(user)

        caldav = CalDAVClient()
        caldav.create_event_raw(user, caldav_path, ICS_WITH_BINARY_ATTACHMENT.decode())

        raw = self._get_raw_event(user, caldav_path, "attach-binary-1")
        assert "Event with inline attachment" in raw
        assert "iVBORw0KGgo" not in raw
        assert "ATTACH" not in raw

    def test_caldav_put_keeps_url_attachment_e2e(self):
        """A normal CalDAV PUT with URL attachment should preserve it."""
        user = factories.UserFactory(email="sanitizer-put-url@example.com")
        caldav_path = self._create_calendar(user)

        caldav = CalDAVClient()
        caldav.create_event_raw(user, caldav_path, ICS_WITH_URL_ATTACHMENT.decode())

        raw = self._get_raw_event(user, caldav_path, "attach-url-1")
        assert "https://example.com/doc.pdf" in raw
        assert "ATTACH" in raw

    def test_caldav_put_truncates_large_description_e2e(self):
        """A normal CalDAV PUT with oversized description should be truncated."""
        user = factories.UserFactory(email="sanitizer-put-desc@example.com")
        caldav_path = self._create_calendar(user)

        caldav = CalDAVClient()
        caldav.create_event_raw(user, caldav_path, ICS_WITH_LARGE_DESCRIPTION.decode())

        raw = self._get_raw_event(user, caldav_path, "large-desc-1")
        assert "Event with huge description" in raw
        assert len(raw) < 150000
        assert "..." in raw

    def test_caldav_put_rejects_oversized_event_e2e(self):
        """A CalDAV PUT exceeding max-resource-size should be rejected (HTTP 507)."""
        user = factories.UserFactory(email="sanitizer-put-oversize@example.com")
        caldav_path = self._create_calendar(user)

        caldav = CalDAVClient()
        with pytest.raises(Exception) as exc_info:
            caldav.create_event_raw(user, caldav_path, ICS_OVERSIZED_EVENT.decode())
        # SabreDAV returns 507 Insufficient Storage
        assert "507" in str(exc_info.value) or "Insufficient" in str(exc_info.value)

    def test_import_rejects_oversized_event_e2e(self):
        """Import of an event exceeding max-resource-size should skip it."""
        user = factories.UserFactory(email="sanitizer-import-oversize@example.com")
        caldav_path = self._create_calendar(user)

        import_service = ICSImportService()
        result = import_service.import_events(user, caldav_path, ICS_OVERSIZED_EVENT)

        assert result.total_events == 1
        assert result.imported_count == 0
        assert result.skipped_count == 1

    def test_caldav_put_truncates_oversized_description_for_non_ics_uri(self):
        """CalDAV places no constraint on the basename of a calendar
        object — clients can use ``UID``, ``UID.ics``, or anything
        else, and SabreDAV's own ``validateICalendar`` runs whenever
        the parent is a calendar collection regardless of extension.
        Pinning the sanitizer on a ``.ics`` suffix would let an
        attacker bypass the binary attachment / description-length /
        max-resource-size limits by uploading the same payload under
        a different name.

        Regression: ``CalendarSanitizerPlugin`` used to gate on
        ``preg_match('/\\.ics$/i', $path)``. The fix gates on the
        parent node being an ``ICalendar`` instead — same check
        SabreDAV's own validator uses.
        """
        user = factories.UserFactory(email="sanitizer-noext@example.com")
        org = factories.OrganizationFactory(external_id="sanitizer-noext-org")
        user.organization = org
        user.save()
        caldav_path = self._create_calendar(user)
        cal_id = _get_cal_id(caldav_path)

        client = APIClient()
        client.force_login(user)

        # 200 KB description — well above the 100 KB cap.
        big = "X" * (200 * 1024)
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Sanitizer//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:sanitizer-noext-1\r\n"
            "DTSTART:20260301T100000Z\r\n"
            "DTEND:20260301T110000Z\r\n"
            "SUMMARY:Sanitizer no-extension test\r\n"
            f"DESCRIPTION:{big}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

        # Use an extension other than .ics — SabreDAV accepts any
        # filename in a calendar collection.
        resp = client.generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/sanitizer-noext-1",
            data=ics,
            content_type="text/calendar",
        )
        if resp.status_code not in (200, 201, 204):
            pytest.skip(
                f"PUT to non-.ics URI was rejected with {resp.status_code} — "
                "the bypass path is already closed by SabreDAV's URI policy."
            )

        get_resp = client.get(
            f"/caldav/calendars/users/{user.email}/{cal_id}/sanitizer-noext-1"
        )
        assert get_resp.status_code == 200, (
            f"GET on stored object failed: {get_resp.status_code}"
        )
        body = get_resp.content.decode("utf-8", errors="ignore")
        # The sanitizer caps DESCRIPTION at 100 KB. A 200 KB description
        # should be visibly truncated.
        assert len(body) < 150 * 1024, (
            "SECURITY: oversized DESCRIPTION was NOT truncated by the "
            f"sanitizer — got {len(body)} bytes back. Sanitizer hook "
            "must run regardless of file extension."
        )


@pytest.mark.xdist_group("caldav")
class TestImportComponentSetFilterE2E:
    """The internal-api ICS import endpoint must filter out components
    whose type is not in the target calendar's
    ``supported-calendar-component-set``.

    The HTTP PUT path enforces the constraint via SabreDAV's
    ``validateICalendar``, but the import endpoint short-circuits
    straight to the backend, so without an explicit filter a user
    could plant VTODOs in their VEVENT-only calendar. The filter is
    a soft skip (not a hard rejection) so a mixed-content ICS file
    can still partially import the supported components, with the
    titles of dropped events surfaced via the ``filtered`` field
    (capped at 100) for the import-modal UI.
    """

    def test_import_filters_vtodo_on_vevent_only_calendar(self):  # pylint: disable=too-many-locals
        """Mixed-content ICS: VEVENT imports, VTODO is filtered, the
        VTODO title is surfaced in ``filtered``."""
        org = factories.OrganizationFactory(external_id="import-vtodo-filter")
        owner, _, cal_path = _create_user_with_vevent_only_calendar(
            org, "owner-vtodo-filter"
        )

        unique = uuid.uuid4().hex[:8]
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Import//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:keep-vevent-{unique}\r\n"
            f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "DTSTART:20260601T100000Z\r\n"
            "DTEND:20260601T110000Z\r\n"
            f"SUMMARY:keep-vevent-{unique}\r\n"
            "END:VEVENT\r\n"
            "BEGIN:VTODO\r\n"
            f"UID:filter-vtodo-{unique}\r\n"
            f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"SUMMARY:filter-me-{unique}\r\n"
            "STATUS:NEEDS-ACTION\r\n"
            "END:VTODO\r\n"
            "END:VCALENDAR\r\n"
        ).encode("utf-8")

        importer = ICSImportService()
        result = importer.import_events(owner, cal_path, ics)

        assert result.imported_count == 1, (
            f"VEVENT should have imported. Result: {result!r}"
        )
        assert result.filtered_count == 1, (
            "VTODO should have been filtered out by component-set "
            f"check. Result: {result!r}"
        )
        assert result.skipped_count >= 1, (
            "filtered events should also count toward skipped_count. "
            f"Result: {result!r}"
        )
        assert f"filter-me-{unique}" in result.filtered, (
            "VTODO summary should appear in the filtered list. "
            f"Got: {result.filtered!r}"
        )
        # Filtering must NOT show up in `errors` — it isn't an error.
        assert not any(f"filter-me-{unique}" in e for e in result.errors), (
            f"Filtered events must not appear in errors. Got: {result.errors!r}"
        )

        # Cross-check via REPORT — the VTODO must NOT be reachable,
        # the VEVENT must.
        owner_client = APIClient()
        owner_client.force_login(owner)
        report_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<C:calendar-query xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:prop><C:calendar-data/></D:prop>"
            '<C:filter><C:comp-filter name="VCALENDAR"/></C:filter>'
            "</C:calendar-query>"
        )
        report_resp = owner_client.generic(
            "REPORT",
            f"/caldav{cal_path}",
            data=report_body,
            content_type="application/xml",
            HTTP_DEPTH="1",
        )
        body = report_resp.content.decode("utf-8", errors="ignore")
        assert f"filter-me-{unique}" not in body, (
            "VTODO was imported AND is reachable via REPORT — the "
            f"component-set filter failed. Body: {body[:1500]}"
        )
        assert f"keep-vevent-{unique}" in body, (
            "VEVENT should have been imported alongside the filtered "
            f"VTODO. Body: {body[:1500]}"
        )

    def test_import_filtered_titles_capped_at_100(self):
        """``filtered`` is capped at 100 entries even when many more
        events are filtered, so a hostile import can't blow up the
        response payload. ``filtered_count`` reflects the true total.
        """
        org = factories.OrganizationFactory(external_id="import-filter-cap")
        owner, _, cal_path = _create_user_with_vevent_only_calendar(org, "owner-cap")

        unique = uuid.uuid4().hex[:8]
        # 150 VTODO entries — well above the 100 cap.
        parts = ["BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//Cap//EN\r\n"]
        for i in range(150):
            parts.append(
                "BEGIN:VTODO\r\n"
                f"UID:cap-vtodo-{unique}-{i}\r\n"
                f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\r\n"
                f"SUMMARY:cap-{unique}-{i}\r\n"
                "STATUS:NEEDS-ACTION\r\n"
                "END:VTODO\r\n"
            )
        parts.append("END:VCALENDAR\r\n")
        ics = "".join(parts).encode("utf-8")

        result = ICSImportService().import_events(owner, cal_path, ics)

        assert result.filtered_count == 150, (
            f"All 150 VTODOs should count as filtered. Got: {result!r}"
        )
        assert len(result.filtered) == 100, (
            "filtered titles list must be capped at 100. "
            f"Got len={len(result.filtered)}"
        )
        assert result.imported_count == 0
        assert result.skipped_count >= 150


def _create_user_with_calendar(org, email_prefix):
    """Create a user with a calendar for E2E tests."""
    user = factories.UserFactory(
        email=f"{email_prefix}@norm-test.com", organization=org
    )
    client = APIClient()
    client.force_login(user)
    service = CalendarService()
    caldav_path = service.create_calendar(user, name=f"{email_prefix}'s Calendar")
    return user, client, caldav_path


def _create_user_with_vevent_only_calendar(org, email_prefix):
    """Create a user + calendar via the production-style internal-api
    endpoint, which constrains the calendar to ``VEVENT`` only.

    The default ``_create_user_with_calendar`` helper goes through the
    caldav library's ``make_calendar`` (a plain MKCALENDAR with no
    ``supported-calendar-component-set``), which makes SabreDAV fall
    back to its built-in default of ``VEVENT,VTODO``. That is NOT
    what real users get — production calendars are created via the
    ``internal-api/calendars`` endpoint with explicit ``['VEVENT']``
    — so any test that wants to assert behavior against the real
    component-set must build the calendar this way.
    """
    user = factories.UserFactory(
        email=f"{email_prefix}@norm-test.com", organization=org
    )
    client = APIClient()
    client.force_login(user)
    http = CalDAVHTTPClient()
    resp = http.internal_request(
        "POST",
        user,
        "internal-api/calendars/",
        json={
            "email": user.email,
            "name": f"{email_prefix}'s Calendar",
            "org_id": str(user.organization_id),
            "calendar_user_type": "INDIVIDUAL",
        },
    )
    assert resp.status_code == 201, (
        f"internal-api calendar creation failed: {resp.status_code} {resp.text[:300]}"
    )
    payload = resp.json()
    calendar_uri = payload.get("calendar_uri") or "default"
    caldav_path = f"/calendars/users/{user.email}/{calendar_uri}/"
    return user, client, caldav_path


def _get_cal_id(caldav_path):
    """Extract calendar ID from path."""
    parts = caldav_path.strip("/").split("/")
    return parts[-1] if len(parts) >= 4 else "default"


@pytest.mark.xdist_group("caldav")
class TestAttendeeNormalizer:
    """AttendeeNormalizerPlugin deduplicates and normalizes attendees."""

    def test_duplicate_attendees_deduplicated(self):
        """Duplicate attendees (same email, different case) are merged."""
        org = factories.OrganizationFactory(external_id="attnorm-dedup")
        user, client, cal_path = _create_user_with_calendar(org, "user-attn")
        cal_id = _get_cal_id(cal_path)

        dtstart = datetime.now() + timedelta(days=1)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:attn-dedup-ev\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Dedup Test\r\n"
            f"ORGANIZER:mailto:{user.email}\r\n"
            "ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:Bob@Example.COM\r\n"
            "ATTENDEE;PARTSTAT=ACCEPTED:mailto:bob@example.com\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        resp = client.generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/attn-dedup-ev.ics",
            data=ical,
            content_type="text/calendar",
        )
        assert resp.status_code in (200, 201, 204), (
            f"PUT should succeed: {resp.status_code}"
        )

        # GET the event back and check attendees
        get_resp = client.generic(
            "GET",
            f"/caldav/calendars/users/{user.email}/{cal_id}/attn-dedup-ev.ics",
        )
        content = get_resp.content.decode("utf-8", errors="ignore")
        # Should have exactly one attendee (deduplicated), with ACCEPTED
        # (higher priority than NEEDS-ACTION)
        attendee_count = content.upper().count("ATTENDEE")
        assert attendee_count == 1, (
            f"Expected 1 attendee after dedup, found {attendee_count}.\n"
            f"Event data: {content}"
        )
        assert "ACCEPTED" in content.upper(), (
            "Dedup should keep the ACCEPTED status (higher priority)"
        )

    def test_attendee_email_normalized_to_lowercase(self):
        """Attendee emails are normalized to lowercase."""
        org = factories.OrganizationFactory(external_id="attnorm-case")
        user, client, cal_path = _create_user_with_calendar(org, "user-attnc")
        cal_id = _get_cal_id(cal_path)

        dtstart = datetime.now() + timedelta(days=1)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:attn-case-ev\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Case Test\r\n"
            f"ORGANIZER:mailto:{user.email}\r\n"
            "ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:Alice@EXAMPLE.COM\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        resp = client.generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/attn-case-ev.ics",
            data=ical,
            content_type="text/calendar",
        )
        assert resp.status_code in (200, 201, 204)

        get_resp = client.generic(
            "GET",
            f"/caldav/calendars/users/{user.email}/{cal_id}/attn-case-ev.ics",
        )
        content = get_resp.content.decode("utf-8", errors="ignore")
        # Email should be lowercased
        assert "alice@example.com" in content.lower(), (
            "Attendee email should be normalized to lowercase"
        )
        assert "Alice@EXAMPLE.COM" not in content, (
            "Original mixed-case email should be normalized"
        )


# ===================================================================
# InternalApiPlugin - Error cases
# ===================================================================
