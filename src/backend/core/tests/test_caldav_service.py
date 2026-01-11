"""Tests for CalDAV service integration."""

from unittest.mock import Mock, patch

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

        dav_client = client._get_client(user)

        # Verify the client is configured correctly
        assert dav_client.username == user.email
        # Password should be empty (None or empty string) for external auth
        assert not dav_client.password or dav_client.password == ""

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

        # Create a calendar
        calendar = service.create_calendar(user, name="My Calendar", color="#ff0000")

        # Verify calendar was created
        assert calendar is not None
        assert calendar.owner == user
        assert calendar.name == "My Calendar"
        assert calendar.color == "#ff0000"
        assert calendar.caldav_path is not None
