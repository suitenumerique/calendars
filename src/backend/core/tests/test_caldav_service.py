"""Tests for CalDAV service integration."""

from django.conf import settings

import pytest

from core import factories
from core.services.caldav_service import CalDAVClient, CalendarService


@pytest.mark.django_db
class TestCalDAVClient:
    """Tests for CalDAVClient authentication and communication."""

    def test_get_client_sends_x_forwarded_user_header(self):
        """Test that DAVClient is configured with X-Forwarded-User header."""
        user = factories.UserFactory(email="test@example.com")
        client = CalDAVClient()

        dav_client = client._get_client(user)  # pylint: disable=protected-access

        # Verify the client is configured correctly
        # Username and password should be None to prevent Basic auth
        assert dav_client.username is None
        assert dav_client.password is None

        # Verify the X-Forwarded-User header is set
        # The caldav library stores headers as a CaseInsensitiveDict
        assert hasattr(dav_client, "headers")
        assert "X-Forwarded-User" in dav_client.headers
        assert dav_client.headers["X-Forwarded-User"] == user.email

    @pytest.mark.skipif(
        not settings.CALDAV_URL,
        reason="CalDAV server URL not configured",
    )
    def test_create_calendar_authenticates_with_caldav_server(self):
        """Test that calendar creation authenticates successfully with CalDAV server."""
        user = factories.UserFactory(email="test@example.com")
        client = CalDAVClient()

        # Try to create a calendar - this should authenticate successfully
        calendar_path = client.create_calendar(
            user, calendar_name="Test Calendar", calendar_id="test-calendar-id"
        )

        # Verify calendar path was returned
        assert calendar_path is not None
        # Email may be URL-encoded in the path (e.g., test%40example.com)
        assert (
            user.email.replace("@", "%40") in calendar_path
            or user.email in calendar_path
        )

    def test_calendar_service_creates_calendar(self):
        """Test that CalendarService can create a calendar through CalDAV server."""
        user = factories.UserFactory(email="test@example.com")
        service = CalendarService()

        # Create a calendar — returns caldav_path string
        caldav_path = service.create_calendar(user, name="My Calendar", color="#ff0000")

        # Verify caldav_path was returned
        assert caldav_path is not None
        assert isinstance(caldav_path, str)
        assert "calendars/" in caldav_path

    @pytest.mark.skipif(
        not settings.CALDAV_URL,
        reason="CalDAV server URL not configured",
    )
    def test_create_calendar_with_color_persists(self):
        """Test that creating a calendar with a color saves it in CalDAV."""
        user = factories.UserFactory(email="color-test@example.com")
        service = CalendarService()
        color = "#e74c3c"

        # Create a calendar with a specific color
        caldav_path = service.create_calendar(user, name="Red Calendar", color=color)

        # Fetch the calendar info and verify the color was persisted
        info = service.caldav.get_calendar_info(user, caldav_path)
        assert info is not None
        assert info["color"] == color
        assert info["name"] == "Red Calendar"
