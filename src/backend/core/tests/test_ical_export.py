"""Tests for iCal export endpoint."""

import uuid

from django.conf import settings
from django.urls import reverse

import pytest
import responses
from rest_framework.status import HTTP_200_OK, HTTP_404_NOT_FOUND, HTTP_502_BAD_GATEWAY
from rest_framework.test import APIClient

from core import factories


@pytest.mark.django_db
class TestICalExport:
    """Tests for ICalExportView."""

    def test_export_with_valid_token_returns_ics(self):
        """Test that a valid token returns iCal data."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()

        # Mock CalDAV server response
        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = subscription.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/api/v1.0/caldav/{caldav_path}?export"

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

            url = reverse("ical-export", kwargs={"token": subscription.token})
            response = client.get(url)

            assert response.status_code == HTTP_200_OK
            assert response["Content-Type"] == "text/calendar; charset=utf-8"
            assert "BEGIN:VCALENDAR" in response.content.decode()
            assert response["Content-Disposition"] is not None
            assert ".ics" in response["Content-Disposition"]

    def test_export_with_invalid_token_returns_404(self):
        """Test that an invalid token returns 404."""
        client = APIClient()
        invalid_token = uuid.uuid4()

        url = reverse("ical-export", kwargs={"token": invalid_token})
        response = client.get(url)

        assert response.status_code == HTTP_404_NOT_FOUND

    def test_export_with_inactive_token_returns_404(self):
        """Test that an inactive token returns 404."""
        subscription = factories.CalendarSubscriptionTokenFactory(is_active=False)
        client = APIClient()

        url = reverse("ical-export", kwargs={"token": subscription.token})
        response = client.get(url)

        assert response.status_code == HTTP_404_NOT_FOUND

    def test_export_updates_last_accessed_at(self):
        """Test that accessing the export updates last_accessed_at."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        assert subscription.last_accessed_at is None

        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = subscription.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/api/v1.0/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            url = reverse("ical-export", kwargs={"token": subscription.token})
            client.get(url)

            subscription.refresh_from_db()
            assert subscription.last_accessed_at is not None

    def test_export_does_not_require_authentication(self):
        """Test that the endpoint is accessible without authentication."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()
        # Not logging in - should still work

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = subscription.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/api/v1.0/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            url = reverse("ical-export", kwargs={"token": subscription.token})
            response = client.get(url)

            assert response.status_code == HTTP_200_OK

    def test_export_sends_correct_headers_to_caldav(self):
        """Test that the proxy sends correct authentication headers to CalDAV."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = subscription.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/api/v1.0/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            url = reverse("ical-export", kwargs={"token": subscription.token})
            client.get(url)

            # Verify headers sent to CalDAV
            assert len(rsps.calls) == 1
            request = rsps.calls[0].request
            assert request.headers["X-Forwarded-User"] == subscription.owner.email
            assert request.headers["X-Api-Key"] == settings.CALDAV_OUTBOUND_API_KEY

    def test_export_handles_caldav_error(self):
        """Test that CalDAV server errors are handled gracefully."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = subscription.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/api/v1.0/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"Internal Server Error",
                status=500,
            )

            url = reverse("ical-export", kwargs={"token": subscription.token})
            response = client.get(url)

            assert response.status_code == HTTP_502_BAD_GATEWAY

    def test_export_sets_security_headers(self):
        """Test that security headers are set correctly."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = subscription.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/api/v1.0/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            url = reverse("ical-export", kwargs={"token": subscription.token})
            response = client.get(url)

            # Verify security headers
            assert response["Cache-Control"] == "no-store, private"
            assert response["Referrer-Policy"] == "no-referrer"

    def test_export_uses_calendar_name_in_filename(self):
        """Test that the export filename uses the calendar_name."""
        subscription = factories.CalendarSubscriptionTokenFactory(
            calendar_name="My Test Calendar"
        )
        client = APIClient()

        with responses.RequestsMock() as rsps:
            caldav_url = settings.CALDAV_URL
            caldav_path = subscription.caldav_path.lstrip("/")
            target_url = f"{caldav_url}/api/v1.0/caldav/{caldav_path}?export"

            rsps.add(
                responses.GET,
                target_url,
                body=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
                status=HTTP_200_OK,
                content_type="text/calendar",
            )

            url = reverse("ical-export", kwargs={"token": subscription.token})
            response = client.get(url)

            assert "My Test Calendar.ics" in response["Content-Disposition"]
