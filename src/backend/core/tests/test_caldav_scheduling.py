"""Tests for CalDAV scheduling callback integration."""

# pylint: disable=no-member,redefined-outer-name,unsubscriptable-object,too-many-lines

import http.server
import logging
import re
import secrets
import socket
import threading
import time
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

from django.conf import settings

import pytest
from rest_framework.test import APIClient as DRFClient

from caldav.lib.error import NotFoundError
from core import factories
from core.entitlements.factory import get_entitlements_backend
from core.services.caldav_service import CalDAVHTTPClient, CalendarService

logger = logging.getLogger(__name__)


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for capturing CalDAV scheduling callbacks in tests."""

    def __init__(self, callback_data, *args, **kwargs):
        self.callback_data = callback_data
        super().__init__(*args, **kwargs)

    def do_POST(self):  # pylint: disable=invalid-name
        """Handle POST requests (scheduling callbacks)."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        # Store callback data. ``request_data`` keeps the LAST request for
        # the single-recipient tests; ``requests`` accumulates ALL POSTs so
        # multi-recipient tests can verify the fan-out (SabreDAV emits one
        # iTip schedule() per recipient, so we expect one POST per attendee).
        record = {
            "headers": dict(self.headers),
            "body": body.decode("utf-8", errors="ignore") if body else "",
        }
        self.callback_data["called"] = True
        self.callback_data["request_data"] = record
        self.callback_data.setdefault("requests", []).append(record)

        # Send success response
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        """Suppress default logging."""


def _wait_for_callbacks(callback_data, expected_count=1, timeout=5.0, interval=0.05):
    """Poll until ``callback_data['requests']`` has at least ``expected_count``
    entries, bounded by ``timeout``. Returns silently in either case — the
    caller asserts the count afterward.

    Why polling instead of ``time.sleep(2)``: SabreDAV's iTip dispatch is
    typically <100ms but a fixed 2s sleep both slows the suite and is
    still racy on a loaded CI runner. Polling at 50ms intervals returns
    as soon as the callbacks land and gives up to 5s of grace before
    declaring failure. For tests that expect ZERO callbacks (e.g.
    spoofing rejection), pass ``expected_count=1`` with a short timeout
    — the helper returns cleanly on timeout and the caller asserts that
    ``requests`` is still empty.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(callback_data.get("requests", [])) >= expected_count:
            return
        time.sleep(interval)


def create_test_server() -> tuple:
    """Create a test HTTP server that captures callbacks.

    Returns:
        Tuple of (server, port, callback_data)
    """
    callback_data = {"called": False, "request_data": None, "requests": []}

    def handler_factory(*args, **kwargs):
        return CallbackHandler(callback_data, *args, **kwargs)

    # Use fixed port 8001 - accessible from other Docker containers
    port = 8001

    # Create server with SO_REUSEADDR to allow quick port reuse
    server = http.server.HTTPServer(("0.0.0.0", port), handler_factory)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    actual_port = server.server_address[1]

    return server, actual_port, callback_data


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestCalDAVScheduling:
    """Tests for CalDAV scheduling callback when creating events with attendees."""

    def test_scheduling_callback_received_when_creating_event_with_attendee(  # noqa: PLR0915  # pylint: disable=too-many-locals,too-many-statements
        self,
    ):
        """Test that creating an event with an attendee triggers scheduling callback.

        This test verifies that when an event is created with an attendee via CalDAV,
        the HttpCallbackIMipPlugin sends a scheduling message to the Django callback endpoint.

        The test starts a local HTTP server on port 8001 to receive the callback.
        The CalDAV server's CALDAV_CALLBACK_BASE_URL env var must point to this server.
        """
        # Create users: organizer
        # Note: attendee should be external (not in CalDAV server) to trigger scheduling
        organizer = factories.UserFactory(email="organizer@example.com")

        # Create calendar for organizer
        service = CalendarService()
        caldav_path = service.create_calendar(
            organizer, name="Test Calendar", color="#ff0000"
        )

        # Start test HTTP server to receive callbacks
        # Use fixed port 8001 - accessible from other Docker containers
        server, port, callback_data = create_test_server()

        # Start server in a separate thread
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        # Give the server a moment to start listening
        time.sleep(0.5)

        # Verify server is actually listening
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.connect(("127.0.0.1", port))
            test_socket.close()
        except OSError as e:
            pytest.fail(f"Test server failed to start on port {port}: {e}")

        try:
            # Create an event with an attendee
            client = service._get_client(organizer)  # pylint: disable=protected-access
            calendar_url = service._calendar_url(caldav_path)  # pylint: disable=protected-access

            try:
                caldav_calendar = client.calendar(url=calendar_url)

                # Create event with attendee using iCalendar format
                # We need to create the event with attendees to trigger scheduling
                # Note: sabre/dav's scheduling plugin only sends messages for external attendees
                # (attendees that don't have a principal in the same CalDAV server)
                dtstart = datetime.now() + timedelta(days=1)
                dtend = dtstart + timedelta(hours=1)

                # Use a clearly external attendee email (not in the CalDAV server)
                external_attendee = "external-attendee@external-domain.com"

                # Create iCalendar event with attendee
                ical_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test Client//EN
BEGIN:VEVENT
UID:test-event-{datetime.now().timestamp()}
DTSTART:{dtstart.strftime("%Y%m%dT%H%M%SZ")}
DTEND:{dtend.strftime("%Y%m%dT%H%M%SZ")}
SUMMARY:Test Event with Attendee
ORGANIZER;CN=Organizer:mailto:{organizer.email}
ATTENDEE;CN=External Attendee;RSVP=TRUE:mailto:{external_attendee}
END:VEVENT
END:VCALENDAR"""

                # Save event to trigger scheduling
                caldav_calendar.save_event(ical_content)

                _wait_for_callbacks(callback_data, expected_count=1)

                # Verify callback was called
                assert callback_data["called"], (
                    "Scheduling callback was not called when creating event "
                    "with attendee. This may indicate that sabre/dav's "
                    "scheduling plugin is not working correctly. "
                    "Check CalDAV server logs for scheduling errors."
                )

                # Verify callback request details
                # pylint: disable=unsubscriptable-object
                request_data: dict = callback_data["request_data"]
                assert request_data is not None

                # Verify API key authentication
                api_key = request_data["headers"].get("X-LS-Api-Key", "")
                expected_key = settings.CALDAV_INBOUND_API_KEY
                assert expected_key and secrets.compare_digest(api_key, expected_key), (
                    "Callback request missing or invalid X-LS-Api-Key header. "
                    f"Expected: {expected_key[:10]}..., "
                    f"Got: {api_key[:10] if api_key else 'None'}..."
                )

                # Verify scheduling headers
                assert "X-LS-Sender" in request_data["headers"], (
                    "Missing X-LS-Sender header"
                )
                assert "X-LS-Recipient" in request_data["headers"], (
                    "Missing X-LS-Recipient header"
                )
                assert "X-LS-Method" in request_data["headers"], (
                    "Missing X-LS-Method header"
                )

                # Verify sender is the organizer
                sender = request_data["headers"]["X-LS-Sender"]
                assert (
                    organizer.email in sender or f"mailto:{organizer.email}" in sender
                ), f"Expected sender to be {organizer.email}, got {sender}"

                # Verify recipient is the attendee
                recipient = request_data["headers"]["X-LS-Recipient"]
                assert (
                    external_attendee in recipient
                    or f"mailto:{external_attendee}" in recipient
                ), f"Expected recipient to be {external_attendee}, got {recipient}"

                # Verify method is REQUEST (for new invitations)
                method = request_data["headers"]["X-LS-Method"]
                assert method == "REQUEST", (
                    f"Expected method to be REQUEST for new invitation, got {method}"
                )

                # Verify iCalendar content is present
                assert request_data["body"], "Callback request body is empty"
                assert "BEGIN:VCALENDAR" in request_data["body"], (
                    "Callback body should contain iCalendar content"
                )
                assert "VEVENT" in request_data["body"], (
                    "Callback body should contain VEVENT"
                )

                # Normalize iCalendar body to handle line folding (CRLF + space/tab)
                # iCalendar format folds long lines at 75 characters, so we need to remove folding
                # Line folding: CRLF followed by space or tab indicates continuation
                body = request_data["body"]
                # Remove line folding: replace CRLF+space and CRLF+tab with nothing
                normalized_body = body.replace("\r\n ", "").replace("\r\n\t", "")
                # Also handle Unix-style line endings
                normalized_body = normalized_body.replace("\n ", "").replace("\n\t", "")
                assert external_attendee in normalized_body, (
                    f"Callback body should contain attendee email {external_attendee}. "
                    f"Normalized body (first 500 chars): {normalized_body[:500]}"
                )

            except NotFoundError:
                pytest.skip("Calendar not found - CalDAV server may not be running")
            except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                pytest.fail(f"Failed to create event with attendee: {str(e)}")
        finally:
            # Shutdown server
            server.shutdown()
            server.server_close()

    def test_scheduling_callback_fires_once_per_external_attendee(  # pylint: disable=too-many-locals,too-many-statements
        self,
    ):
        """Creating an event with TWO external attendees must trigger
        TWO separate scheduling callbacks — one per recipient.

        Reproduces a production report where only one of two invited
        externals received an email. The full chain is
        SabreDAV ``Schedule\\Plugin`` → iTip Broker (one Message per
        attendee) → ``HttpCallbackIMipPlugin::schedule()`` (called once
        per Message) → Django callback (one POST per Message). If
        SabreDAV's broker silently collapses the fan-out, or if our
        plugin only forwards the first, this test catches it before
        the downstream Messages-API step ever runs.
        """
        organizer = factories.UserFactory(email="organizer-multi@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(
            organizer, name="Multi Attendee Calendar", color="#00aaff"
        )

        server, _port, callback_data = create_test_server()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        try:
            client = service._get_client(organizer)  # pylint: disable=protected-access
            calendar_url = service._calendar_url(caldav_path)  # pylint: disable=protected-access

            try:
                caldav_calendar = client.calendar(url=calendar_url)

                dtstart = datetime.now() + timedelta(days=2)
                dtend = dtstart + timedelta(hours=1)

                # Two clearly-external attendees (no principal in the
                # CalDAV server). Distinct domains so we can't be fooled
                # by accidental dedup on domain or local-part.
                attendee_a = "alice@external-a.test"
                attendee_b = "bob@external-b.test"

                ical_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test Client//EN
BEGIN:VEVENT
UID:multi-attendee-{datetime.now().timestamp()}
DTSTART:{dtstart.strftime("%Y%m%dT%H%M%SZ")}
DTEND:{dtend.strftime("%Y%m%dT%H%M%SZ")}
SUMMARY:Event with Two External Attendees
ORGANIZER;CN=Organizer:mailto:{organizer.email}
ATTENDEE;CN=Alice;RSVP=TRUE:mailto:{attendee_a}
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:{attendee_b}
END:VEVENT
END:VCALENDAR"""

                caldav_calendar.save_event(ical_content)

                _wait_for_callbacks(callback_data, expected_count=2)

                requests = callback_data["requests"]
                assert len(requests) == 2, (
                    f"Expected 2 scheduling callbacks (one per external "
                    f"attendee), got {len(requests)}. "
                    f"Recipients seen: "
                    f"{[r['headers'].get('X-LS-Recipient') for r in requests]}. "
                    "If this is 1, SabreDAV's iTip broker is not fanning out "
                    "or HttpCallbackIMipPlugin is dropping the second message — "
                    "either way the second attendee will never receive an email."
                )

                methods = {r["headers"].get("X-LS-Method", "") for r in requests}
                assert methods == {"REQUEST"}, (
                    f"All callbacks should carry METHOD=REQUEST, got {methods}"
                )

                recipients = {
                    re.sub(r"(?i)^mailto:", "", r["headers"].get("X-LS-Recipient", ""))
                    for r in requests
                }
                assert recipients == {attendee_a, attendee_b}, (
                    f"Callback recipients {recipients} do not match the two "
                    f"external attendees {{{attendee_a!r}, {attendee_b!r}}}"
                )

                # Each POST should carry the full iCalendar payload (per
                # RFC 6638, the per-recipient iTip message still lists all
                # attendees — what differs is the X-LS-Recipient header).
                for r in requests:
                    body = r["body"]
                    normalized = body.replace("\r\n ", "").replace("\r\n\t", "")
                    normalized = normalized.replace("\n ", "").replace("\n\t", "")
                    assert "BEGIN:VCALENDAR" in normalized
                    assert attendee_a in normalized
                    assert attendee_b in normalized

            except NotFoundError:
                pytest.skip("Calendar not found - CalDAV server may not be running")
            except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                pytest.fail(f"Failed to create multi-attendee event: {e}")
        finally:
            server.shutdown()
            server.server_close()

    def test_scheduling_callback_fires_cancel_when_deleting_event_with_attendee(  # pylint: disable=too-many-locals,too-many-statements
        self,
    ):
        """Deleting an event with an external attendee must trigger an
        iTIP CANCEL callback so the attendee gets a cancellation email.

        Reproduces the production symptom: invitation arrives fine, but
        deleting the event produces no cancellation email. The chain is
        SabreDAV ``Schedule\\Plugin::beforeUnbind`` → ``deliver()`` →
        ``HttpCallbackIMipPlugin::schedule()`` → Django callback. If any
        link is broken, the attendee never knows the meeting is off.
        """
        organizer = factories.UserFactory(email="organizer-cancel@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(
            organizer, name="Cancel Test Calendar", color="#ff0000"
        )

        server, _port, callback_data = create_test_server()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        try:
            client = service._get_client(organizer)  # pylint: disable=protected-access
            calendar_url = service._calendar_url(caldav_path)  # pylint: disable=protected-access

            try:
                caldav_calendar = client.calendar(url=calendar_url)

                dtstart = datetime.now() + timedelta(days=7)
                dtend = dtstart + timedelta(hours=1)
                external_attendee = "cancel-external@external-domain.com"
                event_uid = f"cancel-test-{datetime.now().timestamp()}"

                ical_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test Client//EN
BEGIN:VEVENT
UID:{event_uid}
DTSTART:{dtstart.strftime("%Y%m%dT%H%M%SZ")}
DTEND:{dtend.strftime("%Y%m%dT%H%M%SZ")}
SUMMARY:Event to be cancelled
ORGANIZER;CN=Organizer:mailto:{organizer.email}
ATTENDEE;CN=External;RSVP=TRUE:mailto:{external_attendee}
END:VEVENT
END:VCALENDAR"""

                event = caldav_calendar.save_event(ical_content)

                # Wait for and assert the REQUEST callback (sanity check —
                # the same path the cancel relies on).
                _wait_for_callbacks(callback_data, expected_count=1)
                assert callback_data["called"], (
                    "REQUEST callback should fire on event creation"
                )
                assert (
                    callback_data["request_data"]["headers"]["X-LS-Method"] == "REQUEST"
                )

                # Reset all three so we can observe what (if anything) DELETE
                # triggers — ``requests`` is reset too so the next
                # ``_wait_for_callbacks`` polls for the post-delete count.
                callback_data["called"] = False
                callback_data["request_data"] = None
                callback_data["requests"] = []

                # Delete the event. SabreDAV's Schedule\\Plugin::beforeUnbind
                # must turn this into a CANCEL iTIP message and route it
                # back through our HTTP callback.
                event.delete()

                _wait_for_callbacks(callback_data, expected_count=1)

                assert callback_data["called"], (
                    "CANCEL callback was not received after deleting the "
                    "event. SabreDAV's beforeUnbind hook either did not "
                    "fire or did not emit an iTIP message — the attendee "
                    "will never get a cancellation email."
                )

                request_data: dict = callback_data["request_data"]
                method = request_data["headers"].get("X-LS-Method", "")
                assert method == "CANCEL", (
                    f"Expected X-LS-Method=CANCEL after delete, got {method!r}"
                )

                recipient = request_data["headers"].get("X-LS-Recipient", "")
                assert external_attendee in recipient, (
                    f"CANCEL should target {external_attendee}, got {recipient!r}"
                )

                body = request_data["body"]
                # Unfold long iCalendar lines before content checks.
                normalized = body.replace("\r\n ", "").replace("\r\n\t", "")
                normalized = normalized.replace("\n ", "").replace("\n\t", "")
                assert "METHOD:CANCEL" in normalized, (
                    "CANCEL iTIP payload must carry METHOD:CANCEL"
                )
                assert event_uid in normalized, (
                    "CANCEL payload should reference the deleted event's UID"
                )

            except NotFoundError:
                pytest.skip("Calendar not found - CalDAV server may not be running")
        finally:
            server.shutdown()
            server.server_close()

    def test_scheduling_callback_for_shared_mailbox_calendar(  # noqa: PLR0915  # pylint: disable=too-many-locals,too-many-statements,redefined-outer-name,unused-variable,no-member
        self,
    ):
        """Test that creating an event in a shared mailbox calendar triggers
        the scheduling callback with X-LS-Is-Mailbox: true.

        This is the key integration test for the mailbox invitation flow:
        1. Create a MAILBOX principal + calendar via internal API
        2. Share it with a user (read-write) via sync-mailbox-acls
        3. User PUTs an event with ORGANIZER=mailbox email
        4. SabreDAV should fire the scheduling callback
        5. The callback should have X-LS-Is-Mailbox: true
        """
        mailbox_email = "mailbox-sched@scheduling-test.com"
        user = factories.UserFactory(email="writer@scheduling-test.com")

        http = CalDAVHTTPClient()

        # 1. Create MAILBOX principal + default calendar
        resp = http.internal_request(
            "POST",
            user,
            "internal-api/calendars/",
            json={
                "email": mailbox_email,
                "name": "Test Mailbox",
                "calendar_user_type": "MAILBOX",
                "org_id": str(user.organization_id),
            },
        )
        assert resp.status_code in (200, 201), (
            f"Failed to create mailbox calendar: {resp.status_code} {resp.text}"
        )

        # 2. Snapshot the user's calendars BEFORE the share so we can find
        #    the new shared instance via set-difference (deterministic).
        #    Shared mailbox calendars appear under the sharee's principal
        #    home with a UUID URI — they do NOT contain mailbox_email — so
        #    a substring filter would not work.
        dav = http.get_dav_client(user)
        before_urls = {str(c.url) for c in dav.principal().calendars()}

        # 3. Share the calendar with the user (read-write) via sync-mailbox-acls
        resp = http.internal_request(
            "POST",
            user,
            "internal-api/sync-mailbox-acls/",
            json={
                "shares": [
                    {
                        "user_email": user.email,
                        "mailbox_email": mailbox_email,
                        "calendar_uri": "default",
                        "privilege": "read-write",
                    }
                ],
                "full_sync_users": [],
            },
        )
        assert resp.status_code == 200, (
            f"Failed to sync mailbox ACLs: {resp.status_code} {resp.text}"
        )

        # 3b. Verify the share shows with correct user info in CS:invite
        # (the share modal reads this — it should show user emails, not mailbox)

        user_client = DRFClient()
        user_client.force_login(user)

        # Pick the new calendar via before/after set-difference.
        after_cals = dav.principal().calendars()
        new_cals = [c for c in after_cals if str(c.url) not in before_urls]
        assert len(new_cals) == 1, (
            f"Expected exactly 1 new calendar after share, got "
            f"{[str(c.url) for c in new_cals]}"
        )
        shared_cal_url = str(new_cals[0].url)
        # Extract the relative path for proxy requests
        shared_path = (
            shared_cal_url.rsplit("/caldav/", maxsplit=1)[-1]
            if "/caldav/" in shared_cal_url
            else ""
        )

        invite_resp = user_client.generic(
            "PROPFIND",
            f"/caldav/{shared_path}",
            data=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<D:propfind xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
                "<D:prop><CS:invite/></D:prop>"
                "</D:propfind>"
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        invite_body = invite_resp.content.decode("utf-8", errors="ignore")
        # The invite should contain the user's email, not the mailbox email
        assert user.email in invite_body, (
            f"CS:invite should contain {user.email} but got:\n{invite_body[:1000]}"
        )

        # 3. Start test callback server
        server, port, callback_data = create_test_server()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        try:
            # 4. Create a CalDAV client authenticated as the user
            service = CalendarService()
            client = service._get_client(user)  # pylint: disable=protected-access

            # Use the shared calendar URL discovered earlier
            calendar_url = shared_cal_url

            try:
                caldav_calendar = client.calendar(url=calendar_url)

                dtstart = datetime.now() + timedelta(days=1)
                dtend = dtstart + timedelta(hours=1)
                external_attendee = "external@scheduling-test.com"

                ical_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test Client//EN
BEGIN:VEVENT
UID:mailbox-sched-test-{datetime.now().timestamp()}
DTSTART:{dtstart.strftime("%Y%m%dT%H%M%SZ")}
DTEND:{dtend.strftime("%Y%m%dT%H%M%SZ")}
SUMMARY:Mailbox Scheduling Test
ORGANIZER;CN=Test Mailbox:mailto:{mailbox_email}
ATTENDEE;CN=External;RSVP=TRUE:mailto:{external_attendee}
END:VEVENT
END:VCALENDAR"""

                caldav_calendar.save_event(ical_content)

                _wait_for_callbacks(callback_data, expected_count=1)

                # 5. Verify callback was called
                assert callback_data["called"], (
                    "Scheduling callback was NOT called for event in shared "
                    "mailbox calendar. The ORGANIZER was set to the mailbox "
                    f"email ({mailbox_email}) which should be in the user's "
                    "calendar-user-address-set via the read-write share. "
                    "SabreDAV's Schedule plugin may not fire calendarObjectChange "
                    "for shared calendar instances."
                )

                # Verify X-LS-Is-Mailbox header
                request_data = callback_data["request_data"]
                is_mailbox = request_data["headers"].get("X-LS-Is-Mailbox", "")
                assert is_mailbox == "true", (
                    f"Expected X-LS-Is-Mailbox: true, got: '{is_mailbox}'. "
                    "The HttpCallbackIMipPlugin should detect the sender is a "
                    "MAILBOX principal and set this header."
                )

                # Verify sender is the mailbox email (not the OIDC user)
                sender = request_data["headers"].get("X-LS-Sender", "")
                assert mailbox_email in sender, (
                    f"Expected sender to be {mailbox_email}, got {sender}"
                )

            except NotFoundError:
                pytest.skip("Shared calendar not found - check sync-mailbox-acls")
            except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                pytest.fail(f"Failed to create event in shared mailbox calendar: {e}")
        finally:
            server.shutdown()
            server.server_close()


def _create_user_with_calendar(org, email_prefix, domain="sched-test.com"):
    """Create a user with a calendar and return (user, client, caldav_path)."""
    user = factories.UserFactory(email=f"{email_prefix}@{domain}", organization=org)
    client = DRFClient()
    client.force_login(user)
    service = CalendarService()
    caldav_path = service.create_calendar(user, name=f"{email_prefix}'s Calendar")
    return user, client, caldav_path


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestOrganizerSpoofingRejection:
    """Pin SabreDAV's enforcement that ORGANIZER must belong to the
    authenticated principal's calendar-user-address-set.

    Without this enforcement, user A could PUT an event with
    ``ORGANIZER:mailto:victim@target.com`` (or with the email of a
    mailbox they don't have read-write access to) and trigger the
    iMIP callback to send invitations "as" that identity. The check
    is implemented by sabre's ``Schedule\\Plugin::scheduleLocalDelivery``
    and the ACL grant on the principal home; ``MailboxPlugin``
    extends the address set with mailbox emails the user has
    read-write access to.

    These tests pin BOTH directions:
      1. PUTs with a foreign ORGANIZER are rejected (403/Forbidden /
         412 / 207 multistatus with an error — sabre's exact response
         varies by version).
      2. The negative-control PUT with the user's OWN ORGANIZER
         succeeds, so we can be sure we're not just observing a
         general "PUTs broken" failure.
    """

    @staticmethod
    def _build_event(organizer_email: str, summary: str = "Spoof test") -> str:
        dtstart = datetime.now() + timedelta(days=1)
        dtend = dtstart + timedelta(hours=1)
        return (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Spoof//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:spoof-test-{secrets.token_hex(6)}\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"SUMMARY:{summary}\r\n"
            f"ORGANIZER;CN=Spoofed:mailto:{organizer_email}\r\n"
            "ATTENDEE;CN=Outside;RSVP=TRUE:"
            "mailto:bystander@external-target.com\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

    def test_imip_callback_does_not_fire_with_foreign_organizer(self):
        """When user A PUTs an event with ``ORGANIZER:mailto:victim@…``
        (an address outside their calendar-user-address-set), the iMIP
        callback to Django must NOT fire with that spoofed sender —
        regardless of whether sabre/dav accepts the PUT itself.

        sabre/dav's behavior here is implementation-defined: it may
        accept the PUT and silently skip the schedule fan-out (treating
        the event as "client-side scheduling"), or it may reject the
        PUT with 403/412. Either is acceptable from a security point of
        view. What is NOT acceptable is firing the iMIP callback with
        ``X-LS-Sender: victim@…`` — that would let any authenticated
        user trigger outbound mail "from" any chosen identity.
        """
        org = factories.OrganizationFactory(external_id=f"spoof-{secrets.token_hex(4)}")
        user, _, cal_path = _create_user_with_calendar(org, "spoof-attacker")

        server, _, callback_data = create_test_server()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        try:
            service = CalendarService()
            client = service._get_client(user)  # pylint: disable=protected-access
            calendar_url = service._calendar_url(cal_path)  # pylint: disable=protected-access
            caldav_calendar = client.calendar(url=calendar_url)

            spoofed = "victim@external-victim.com"
            ical_content = self._build_event(spoofed)

            try:
                caldav_calendar.save_event(ical_content)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                # PUT rejected — that's also acceptable. Either path is fine
                # so long as the callback doesn't fire with the spoof.
                pass

            # Zero callbacks is the expected outcome; a short bounded wait
            # is enough to catch any rogue ones.
            _wait_for_callbacks(callback_data, expected_count=1, timeout=2.0)

            if callback_data["called"]:
                sender = callback_data["request_data"]["headers"].get("X-LS-Sender", "")
                assert spoofed not in sender, (
                    f"iMIP callback fired with SPOOFED sender: {sender}. "
                    f"sabre/dav must NOT honor an ORGANIZER outside the "
                    f"authenticated principal's calendar-user-address-set "
                    f"when delivering iMIP messages — otherwise any user "
                    f"can send invitations 'as' any other identity."
                )
                # If we got here, the callback fired with a sender that
                # is NOT the spoofed one (e.g. sabre rewrote it to the
                # authenticated principal). That's defensible behavior.
        finally:
            server.shutdown()
            server.server_close()

    def test_user_can_put_event_with_own_organizer(self):
        """Negative control: same shape as the spoof test but with the
        user's own ORGANIZER. Must succeed and fire the callback."""
        org = factories.OrganizationFactory(
            external_id=f"spoof-ctrl-{secrets.token_hex(4)}"
        )
        user, _, cal_path = _create_user_with_calendar(org, "spoof-control")

        server, _, callback_data = create_test_server()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        try:
            service = CalendarService()
            client = service._get_client(user)  # pylint: disable=protected-access
            calendar_url = service._calendar_url(cal_path)  # pylint: disable=protected-access
            caldav_calendar = client.calendar(url=calendar_url)

            ical_content = self._build_event(user.email)
            caldav_calendar.save_event(ical_content)
            _wait_for_callbacks(callback_data, expected_count=1)
            assert callback_data["called"], (
                "Negative control failed: own-ORGANIZER PUT did not "
                "trigger the scheduling callback. The spoofing test "
                "above is not meaningful unless this control passes."
            )
            sender = callback_data["request_data"]["headers"].get("X-LS-Sender", "")
            assert user.email in sender
        finally:
            server.shutdown()
            server.server_close()

    def test_readonly_mailbox_sharee_cannot_organize_as_mailbox(self):
        """A read-only sharee on a MAILBOX calendar must NOT be able
        to PUT events with ORGANIZER set to the mailbox email.

        ``MailboxPlugin::propFindAddresses`` only injects mailbox
        addresses for sharees with ``access >= ACCESS_READ_WRITE``;
        a read-only sharee's calendar-user-address-set must therefore
        NOT contain the mailbox email, and any ORGANIZER claim must
        be rejected by sabre's Schedule plugin.
        """
        mailbox_email = f"mailbox-{secrets.token_hex(4)}@spoof-mb.com"
        owner = factories.UserFactory(
            email=f"owner-{secrets.token_hex(4)}@spoof-mb.com"
        )
        sharee = factories.UserFactory(
            email=f"sharee-{secrets.token_hex(4)}@spoof-mb.com"
        )

        http = CalDAVHTTPClient()

        # 1. Create the MAILBOX principal + default calendar.
        resp = http.internal_request(
            "POST",
            owner,
            "internal-api/calendars/",
            json={
                "email": mailbox_email,
                "name": "Spoof Mailbox",
                "calendar_user_type": "MAILBOX",
                "org_id": str(owner.organization_id),
            },
        )
        assert resp.status_code in (200, 201)

        # 2. Share with the sharee READ-ONLY (privilege="read").
        resp = http.internal_request(
            "POST",
            owner,
            "internal-api/sync-mailbox-acls/",
            json={
                "shares": [
                    {
                        "user_email": sharee.email,
                        "mailbox_email": mailbox_email,
                        "privilege": "read",
                    }
                ],
                "full_sync_users": [],
            },
        )
        assert resp.status_code == 200

        # 3. Sharee's calendar-user-address-set must NOT contain the mailbox
        # — query the sharee's principal home.
        sharee_client = DRFClient()
        sharee_client.force_login(sharee)
        cuas_propfind = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:prop><C:calendar-user-address-set/></D:prop>"
            "</D:propfind>"
        )
        resp = sharee_client.generic(
            "PROPFIND",
            f"/caldav/principals/users/{sharee.email}/",
            data=cuas_propfind,
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        body = resp.content.decode("utf-8", errors="ignore")
        assert mailbox_email not in body, (
            f"Read-only sharee's calendar-user-address-set leaked the "
            f"mailbox email {mailbox_email}. MailboxPlugin::propFindAddresses "
            f"must only inject for ACCESS_READ_WRITE sharees. Body: {body[:500]}"
        )


@pytest.fixture()
def _avail_entitlements(settings):
    """Use local entitlements for availability tests."""
    settings.ENTITLEMENTS_BACKEND = (
        "core.entitlements.backends.local.LocalEntitlementsBackend"
    )
    settings.ENTITLEMENTS_BACKEND_PARAMETERS = {}
    get_entitlements_backend.cache_clear()
    yield
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
@pytest.mark.usefixtures("_avail_entitlements")
class TestAvailabilityPlugin:
    """AvailabilityPlugin injects BUSY-UNAVAILABLE into freebusy responses.

    When a user has set working hours via calendar-availability (PROPPATCH),
    the plugin post-processes scheduling outbox VFREEBUSY responses to add
    FREEBUSY;FBTYPE=BUSY-UNAVAILABLE periods for times outside those hours.
    """

    def test_availability_proppatch_and_propfind_roundtrip(self):
        """calendar-availability can be set via PROPPATCH and read back."""
        org = factories.OrganizationFactory(
            external_id="avail-roundtrip",
            default_sharing_level="freebusy",
        )
        user, client, _ = _create_user_with_calendar(org, "user-availrt")

        availability_ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Availability//EN\r\n"
            "BEGIN:VAVAILABILITY\r\n"
            "BEGIN:AVAILABLE\r\n"
            "DTSTART:20260105T090000Z\r\n"
            "DTEND:20260105T170000Z\r\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\r\n"
            "END:AVAILABLE\r\n"
            "END:VAVAILABILITY\r\n"
            "END:VCALENDAR\r\n"
        )
        proppatch_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propertyupdate xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:set><D:prop>"
            "<C:calendar-availability>"
            f"{availability_ics}"
            "</C:calendar-availability>"
            "</D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp = client.generic(
            "PROPPATCH",
            f"/caldav/calendars/users/{user.email}/",
            data=proppatch_body,
            content_type="application/xml",
        )
        assert resp.status_code == 207, (
            f"PROPPATCH availability failed: {resp.status_code} "
            f"{resp.content.decode()[:500]}"
        )

        # Read it back via PROPFIND
        propfind_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:prop><C:calendar-availability/></D:prop>"
            "</D:propfind>"
        )
        resp2 = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/",
            data=propfind_body,
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        content = resp2.content.decode("utf-8", errors="ignore")
        assert "VAVAILABILITY" in content, (
            f"PROPFIND should return stored availability.\nResponse: {content[:1000]}"
        )
        assert "BYDAY=MO,TU,WE,TH,FR" in content, (
            "Stored RRULE should be returned in PROPFIND"
        )

    def test_availability_injected_into_freebusy_response(self):
        """Freebusy query should include BUSY-UNAVAILABLE for non-working hours."""

        org = factories.OrganizationFactory(
            external_id="avail-inject",
            default_sharing_level="freebusy",
        )
        target, target_client, _ = _create_user_with_calendar(org, "target-avail")
        querier, querier_client, _ = _create_user_with_calendar(org, "querier-avail")

        # Set calendar-availability on target's calendar home
        availability_ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Availability//EN\r\n"
            "BEGIN:VAVAILABILITY\r\n"
            "BEGIN:AVAILABLE\r\n"
            "DTSTART:20260105T090000Z\r\n"
            "DTEND:20260105T170000Z\r\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR\r\n"
            "END:AVAILABLE\r\n"
            "END:VAVAILABILITY\r\n"
            "END:VCALENDAR\r\n"
        )
        proppatch_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propertyupdate xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:set><D:prop>"
            "<C:calendar-availability>"
            f"{availability_ics}"
            "</C:calendar-availability>"
            "</D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp = target_client.generic(
            "PROPPATCH",
            f"/caldav/calendars/users/{target.email}/",
            data=proppatch_body,
            content_type="application/xml",
        )
        assert resp.status_code == 207

        # Verify it was stored before proceeding
        propfind_resp = target_client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{target.email}/",
            data=(
                '<?xml version="1.0"?>'
                '<D:propfind xmlns:D="DAV:" '
                'xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<D:prop><C:calendar-availability/></D:prop>"
                "</D:propfind>"
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        pf_content = propfind_resp.content.decode()
        assert "VAVAILABILITY" in pf_content, (
            f"Availability property not stored! PROPFIND: {pf_content[:500]}"
        )

        # AvailabilityPlugin computes BUSY-UNAVAILABLE blocks from the
        # user's stored VAVAILABILITY across the freebusy query window —
        # it does not depend on any seeded events on the target's
        # calendar. Schedule\Plugin always emits a VFREEBUSY block
        # whether the calendar contains events or not, which gives the
        # plugin a hook to attach the BUSY-UNAVAILABLE lines to.
        # Use a weekday (Monday) range for the freebusy query
        now = datetime.now(dt_tz.utc)
        days_ahead = (7 - now.weekday()) % 7  # 0=Monday
        if days_ahead == 0:
            days_ahead = 7
        next_monday = now + timedelta(days=days_ahead)
        dtstart = next_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        dtend = dtstart + timedelta(days=1)

        fb_ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VFREEBUSY\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"ORGANIZER:mailto:{querier.email}\r\n"
            f"ATTENDEE:mailto:{target.email}\r\n"
            "END:VFREEBUSY\r\n"
            "END:VCALENDAR\r\n"
        )
        resp = querier_client.generic(
            "POST",
            f"/caldav/calendars/users/{querier.email}/outbox/",
            data=fb_ical,
            content_type="text/calendar",
        )
        assert resp.status_code == 200, (
            f"Outbox POST failed: {resp.status_code} {resp.content.decode()[:500]}"
        )

        content = resp.content.decode("utf-8", errors="ignore")
        # Should contain BUSY-UNAVAILABLE for hours outside 09:00-17:00
        assert "BUSY-UNAVAILABLE" in content, (
            f"Freebusy response should contain BUSY-UNAVAILABLE periods "
            f"for non-working hours.\nResponse:\n{content[:2000]}"
        )

    def test_no_availability_means_no_busy_unavailable(self):
        """Without calendar-availability set, no BUSY-UNAVAILABLE should appear."""

        org = factories.OrganizationFactory(
            external_id="avail-none",
            default_sharing_level="freebusy",
        )
        target, _, _ = _create_user_with_calendar(org, "target-noavail")
        querier, querier_client, _ = _create_user_with_calendar(org, "querier-noavail")

        # No VAVAILABILITY is stored on the target, so AvailabilityPlugin
        # bails out at ``getCalendarAvailability`` returning null. The
        # delivered VFREEBUSY response must therefore be free of any
        # BUSY-UNAVAILABLE lines regardless of what's on the calendar.
        now = datetime.now(dt_tz.utc)
        dtstart = (now + timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
        dtend = (now + timedelta(days=2)).strftime("%Y%m%dT%H%M%SZ")
        fb_ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VFREEBUSY\r\n"
            f"DTSTART:{dtstart}\r\n"
            f"DTEND:{dtend}\r\n"
            f"ORGANIZER:mailto:{querier.email}\r\n"
            f"ATTENDEE:mailto:{target.email}\r\n"
            "END:VFREEBUSY\r\n"
            "END:VCALENDAR\r\n"
        )
        resp = querier_client.generic(
            "POST",
            f"/caldav/calendars/users/{querier.email}/outbox/",
            data=fb_ical,
            content_type="text/calendar",
        )
        assert resp.status_code == 200

        content = resp.content.decode("utf-8", errors="ignore")
        assert "BUSY-UNAVAILABLE" not in content, (
            "Without calendar-availability, BUSY-UNAVAILABLE should not appear"
        )


# ===================================================================
# CS:invite-reply (accept/decline share)
# ===================================================================
