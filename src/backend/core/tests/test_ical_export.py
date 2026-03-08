"""Tests for iCal export endpoint (using Channel type=ical-feed)."""

from django.conf import settings

import pytest
import responses
from rest_framework.status import HTTP_200_OK, HTTP_404_NOT_FOUND, HTTP_502_BAD_GATEWAY
from rest_framework.test import APIClient

from core import factories
from core.models import uuid_to_urlsafe


@pytest.mark.django_db
class TestICalExport:
    """Tests for ICalExportView."""

    def _ical_url(self, channel):
        """Build the iCal export URL for a channel."""
        token = channel.encrypted_settings["token"]
        short_id = uuid_to_urlsafe(channel.pk)
        return f"/ical/{short_id}/{token}/calendar.ics"

    def test_export_with_valid_token_returns_ics(self):
        """Test that a valid token returns iCal data."""
        channel = factories.ICalFeedChannelFactory()
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = channel.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/caldav/{caldav_path}?export"

            ics_content = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//SabreDAV//SabreDAV//EN
BEGIN:VEVENT
UID:test-event-123
DTSTART:20240101T100000Z
DTEND:20240101T110000Z
SUMMARY:Test Event
END:VEVENT
END:VCALENDAR"""

            rsps.add(
                responses.GET,
                target_url,
                body=ics_content,
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            response = client.get(self._ical_url(channel))

            assert response.status_code == HTTP_200_OK
            assert response["Content-Type"] == "text/calendar; charset=utf-8"
            assert "BEGIN:VCALENDAR" in response.content.decode()
            assert response["Content-Disposition"] is not None
            assert ".ics" in response["Content-Disposition"]

    def test_export_with_invalid_token_returns_404(self):
        """Test that an invalid token returns 404."""
        channel = factories.ICalFeedChannelFactory()
        short_id = uuid_to_urlsafe(channel.pk)
        client = APIClient()
        response = client.get(f"/ical/{short_id}/WrongTokenHere123/calendar.ics")
        assert response.status_code == HTTP_404_NOT_FOUND

    def test_export_with_invalid_channel_id_returns_404(self):
        """Test that a nonexistent channel ID returns 404."""
        client = APIClient()
        # base62-encoded zero UUID
        response = client.get("/ical/0/SomeToken123/calendar.ics")
        assert response.status_code == HTTP_404_NOT_FOUND

    def test_export_with_inactive_token_returns_404(self):
        """Test that an inactive token returns 404."""
        channel = factories.ICalFeedChannelFactory(is_active=False)
        client = APIClient()

        response = client.get(self._ical_url(channel))
        assert response.status_code == HTTP_404_NOT_FOUND

    def test_export_updates_last_used_at(self):
        """Test that accessing the export updates last_used_at."""
        channel = factories.ICalFeedChannelFactory()
        assert channel.last_used_at is None

        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = channel.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            client.get(self._ical_url(channel))

            channel.refresh_from_db()
            assert channel.last_used_at is not None

    def test_export_does_not_require_authentication(self):
        """Test that the endpoint is accessible without authentication."""
        channel = factories.ICalFeedChannelFactory()
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = channel.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            response = client.get(self._ical_url(channel))
            assert response.status_code == HTTP_200_OK

    def test_export_sends_correct_headers_to_caldav(self):
        """Test that the proxy sends correct authentication headers to CalDAV."""
        channel = factories.ICalFeedChannelFactory()
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = channel.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            client.get(self._ical_url(channel))

            assert len(rsps.calls) == 1
            request = rsps.calls[0].request
            assert request.headers["X-Forwarded-User"] == channel.user.email
            assert request.headers["X-Api-Key"] == settings.CALDAV_OUTBOUND_API_KEY

    def test_export_handles_caldav_error(self):
        """Test that CalDAV server errors are handled gracefully."""
        channel = factories.ICalFeedChannelFactory()
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = channel.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"Internal Server Error",
                status=500,
            )

            response = client.get(self._ical_url(channel))
            assert response.status_code == HTTP_502_BAD_GATEWAY

    def test_export_sets_security_headers(self):
        """Test that security headers are set correctly."""
        channel = factories.ICalFeedChannelFactory()
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = channel.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            response = client.get(self._ical_url(channel))

            assert response["Cache-Control"] == "no-store, private"
            assert response["Referrer-Policy"] == "no-referrer"

    def test_export_uses_calendar_name_in_filename(self):
        """Test that the export filename uses the calendar_name from settings."""
        channel = factories.ICalFeedChannelFactory(
            settings={"role": "reader", "calendar_name": "My Test Calendar"}
        )
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = channel.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            response = client.get(self._ical_url(channel))
            assert "my-test-calendar.ics" in response["Content-Disposition"]

    def test_non_ical_feed_channel_returns_404(self):
        """Test that a valid token for a non-ical-feed channel returns 404."""
        channel = factories.ChannelFactory()  # type="caldav" (default)
        token = channel.encrypted_settings["token"]
        short_id = uuid_to_urlsafe(channel.pk)
        client = APIClient()

        response = client.get(f"/ical/{short_id}/{token}/calendar.ics")
        assert response.status_code == HTTP_404_NOT_FOUND
