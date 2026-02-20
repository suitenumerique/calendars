"""Tests for CalDAV scheduling callback integration."""

import http.server
import logging
import os
import secrets
import socket
import threading
import time
from datetime import datetime, timedelta

from django.conf import settings

import pytest

from caldav.lib.error import NotFoundError
from core import factories
from core.services.caldav_service import CalendarService

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

        # Store callback data
        self.callback_data["called"] = True
        self.callback_data["request_data"] = {
            "headers": dict(self.headers),
            "body": body.decode("utf-8", errors="ignore") if body else "",
        }

        # Send success response
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        """Suppress default logging."""


def create_test_server() -> tuple:
    """Create a test HTTP server that captures callbacks.

    Returns:
        Tuple of (server, port, callback_data)
    """
    callback_data = {"called": False, "request_data": None}

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
class TestCalDAVScheduling:
    """Tests for CalDAV scheduling callback when creating events with attendees."""

    @pytest.mark.skipif(
        not settings.CALDAV_URL,
        reason="CalDAV server URL not configured - integration test requires real server",
    )
    def test_scheduling_callback_received_when_creating_event_with_attendee(  # noqa: PLR0915  # pylint: disable=too-many-locals,too-many-statements
        self,
    ):
        """Test that creating an event with an attendee triggers scheduling callback.

        This test verifies that when an event is created with an attendee via CalDAV,
        the HttpCallbackIMipPlugin sends a scheduling message to the Django callback endpoint.

        The test starts a local HTTP server to receive the callback, and passes the server URL
        to the CalDAV server via the X-CalDAV-Callback-URL header.
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

        # In Docker Compose, use the container hostname; on bare host (CI), use localhost
        callback_host = os.environ.get("CALDAV_CALLBACK_HOST", "backend-test")
        callback_url = f"http://{callback_host}:{port}/"

        try:
            # Create an event with an attendee
            client = service.caldav._get_client(organizer)  # pylint: disable=protected-access
            calendar_url = f"{settings.CALDAV_URL}{caldav_path}"

            # Add custom callback URL header to the client
            # The CalDAV server will use this URL for the callback
            client.headers["X-CalDAV-Callback-URL"] = callback_url

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

                # Give the callback a moment to be called (scheduling may be async)
                # sabre/dav processes scheduling synchronously during the request
                time.sleep(2)

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
                api_key = request_data["headers"].get("X-Api-Key", "")
                expected_key = settings.CALDAV_INBOUND_API_KEY
                assert expected_key and secrets.compare_digest(api_key, expected_key), (
                    "Callback request missing or invalid X-Api-Key header. "
                    f"Expected: {expected_key[:10]}..., "
                    f"Got: {api_key[:10] if api_key else 'None'}..."
                )

                # Verify scheduling headers
                assert "X-CalDAV-Sender" in request_data["headers"], (
                    "Missing X-CalDAV-Sender header"
                )
                assert "X-CalDAV-Recipient" in request_data["headers"], (
                    "Missing X-CalDAV-Recipient header"
                )
                assert "X-CalDAV-Method" in request_data["headers"], (
                    "Missing X-CalDAV-Method header"
                )

                # Verify sender is the organizer
                sender = request_data["headers"]["X-CalDAV-Sender"]
                assert (
                    organizer.email in sender or f"mailto:{organizer.email}" in sender
                ), f"Expected sender to be {organizer.email}, got {sender}"

                # Verify recipient is the attendee
                recipient = request_data["headers"]["X-CalDAV-Recipient"]
                assert (
                    external_attendee in recipient
                    or f"mailto:{external_attendee}" in recipient
                ), f"Expected recipient to be {external_attendee}, got {recipient}"

                # Verify method is REQUEST (for new invitations)
                method = request_data["headers"]["X-CalDAV-Method"]
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
