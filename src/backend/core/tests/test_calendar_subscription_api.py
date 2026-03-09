"""Tests for iCal feed channel creation via the channels API."""

import pytest
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)
from rest_framework.test import APIClient

from core import factories
from core.models import Channel

CHANNELS_URL = "/api/v1.0/channels/"


@pytest.mark.django_db
class TestICalFeedChannels:
    """Tests for ical-feed channel creation via ChannelViewSet."""

    def test_create_ical_feed_channel(self):
        """Test creating an ical-feed channel for a calendar."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/users/{user.email}/test-calendar-uuid/"
        client = APIClient()
        client.force_login(user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "My Test Calendar",
                "type": "ical-feed",
                "caldav_path": caldav_path,
                "calendar_name": "My Test Calendar",
            },
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED
        assert "token" in response.data
        assert "url" in response.data
        assert "/ical/" in response.data["url"]
        assert ".ics" in response.data["url"]
        assert response.data["caldav_path"] == caldav_path
        assert response.data["type"] == "ical-feed"

        # Verify channel was created in database
        assert Channel.objects.filter(
            user=user, caldav_path=caldav_path, type="ical-feed"
        ).exists()

    def test_create_ical_feed_normalizes_path(self):
        """Test that caldav_path is normalized to have leading/trailing slashes."""
        user = factories.UserFactory()
        caldav_path = f"calendars/users/{user.email}/test-uuid"
        client = APIClient()
        client.force_login(user)

        response = client.post(
            CHANNELS_URL,
            {"name": "Cal", "type": "ical-feed", "caldav_path": caldav_path},
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED
        assert (
            response.data["caldav_path"] == f"/calendars/users/{user.email}/test-uuid/"
        )

    def test_create_ical_feed_returns_existing(self):
        """Test that creating an ical-feed channel when one exists returns it."""
        channel = factories.ICalFeedChannelFactory()
        client = APIClient()
        client.force_login(channel.user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Updated Name",
                "type": "ical-feed",
                "caldav_path": channel.caldav_path,
                "calendar_name": "Updated Name",
            },
            format="json",
        )

        assert response.status_code == HTTP_200_OK
        # Name should be updated
        channel.refresh_from_db()
        assert channel.settings["calendar_name"] == "Updated Name"

    def test_list_ical_feed_channels(self):
        """Test filtering channels by type=ical-feed."""
        user = factories.UserFactory()
        client = APIClient()
        client.force_login(user)

        # Create one ical-feed and one caldav channel
        client.post(
            CHANNELS_URL,
            {
                "name": "Feed",
                "type": "ical-feed",
                "caldav_path": f"/calendars/users/{user.email}/cal1/",
            },
            format="json",
        )
        client.post(
            CHANNELS_URL,
            {"name": "CalDAV Channel"},
            format="json",
        )

        # Filter by type
        response = client.get(CHANNELS_URL, {"type": "ical-feed"})
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["type"] == "ical-feed"

        # Without filter, both show up
        response = client.get(CHANNELS_URL)
        assert len(response.data) == 2

    def test_delete_ical_feed_channel(self):
        """Test deleting an ical-feed channel."""
        channel = factories.ICalFeedChannelFactory()
        client = APIClient()
        client.force_login(channel.user)

        response = client.delete(f"{CHANNELS_URL}{channel.pk}/")

        assert response.status_code == HTTP_204_NO_CONTENT
        assert not Channel.objects.filter(pk=channel.pk).exists()

    def test_non_owner_cannot_create_ical_feed(self):
        """Test that users cannot create ical-feed channels for others' calendars."""
        user = factories.UserFactory()
        other_user = factories.UserFactory()
        caldav_path = f"/calendars/users/{other_user.email}/test-calendar/"
        client = APIClient()
        client.force_login(user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Stolen",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_non_owner_cannot_list_others_channels(self):
        """Test that users only see their own channels."""
        factories.ICalFeedChannelFactory()
        other_user = factories.UserFactory()
        client = APIClient()
        client.force_login(other_user)

        response = client.get(CHANNELS_URL, {"type": "ical-feed"})
        assert response.status_code == HTTP_200_OK
        assert len(response.data) == 0

    def test_unauthenticated_cannot_create(self):
        """Test that unauthenticated users cannot create channels."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/users/{user.email}/test-calendar/"
        client = APIClient()

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Feed",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )

        assert response.status_code == HTTP_401_UNAUTHORIZED

    def test_regenerate_token(self):
        """Test regenerating a token by delete + create."""
        channel = factories.ICalFeedChannelFactory()
        old_token = channel.encrypted_settings["token"]
        client = APIClient()
        client.force_login(channel.user)

        # Delete old channel
        response = client.delete(f"{CHANNELS_URL}{channel.pk}/")
        assert response.status_code == HTTP_204_NO_CONTENT

        # Create new one for the same path
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Feed",
                "type": "ical-feed",
                "caldav_path": channel.caldav_path,
            },
            format="json",
        )
        assert response.status_code == HTTP_201_CREATED
        assert response.data["token"] != old_token

    def test_unique_constraint_per_owner_calendar(self):
        """Test that only one ical-feed channel exists per owner+caldav_path."""
        channel = factories.ICalFeedChannelFactory()
        client = APIClient()
        client.force_login(channel.user)

        # Try to create another - should return existing
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Duplicate",
                "type": "ical-feed",
                "caldav_path": channel.caldav_path,
            },
            format="json",
        )

        assert response.status_code == HTTP_200_OK
        assert Channel.objects.filter(user=channel.user, type="ical-feed").count() == 1

    def test_url_contains_slugified_calendar_name(self):
        """Test that the URL contains the slugified calendar name."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/users/{user.email}/cal/"
        client = APIClient()
        client.force_login(user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "My Awesome Calendar",
                "type": "ical-feed",
                "caldav_path": caldav_path,
                "calendar_name": "My Awesome Calendar",
            },
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED
        assert "my-awesome-calendar.ics" in response.data["url"]


@pytest.mark.django_db
class TestPathInjectionProtection:
    """
    Security tests for CalDAV path injection protection.

    These tests verify that malicious paths are rejected to prevent:
    - Path traversal attacks (../)
    - Query parameter injection
    - Fragment injection
    - Access to other users' calendars via path manipulation
    """

    @pytest.mark.parametrize(
        "malicious_suffix",
        [
            "../other-calendar/",
            "../../etc/passwd/",
            "..%2F..%2Fetc%2Fpasswd/",
            "uuid?export=true/",
            "uuid?admin=true/",
            "uuid#malicious/",
            "uuid;rm -rf/",
            "uuid|cat /etc/passwd/",
            "uuid$(whoami)/",
            "uuid`whoami`/",
            "uuid//",
            "/uuid/",
            "uuid with spaces/",
            "uuid\ttab/",
            "uuid\u002e\u002e/",
        ],
    )
    def test_create_rejects_malicious_calendar_id(self, malicious_suffix):
        """Test that malicious calendar IDs in paths are rejected."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/users/{user.email}/{malicious_suffix}"
        client = APIClient()
        client.force_login(user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Bad",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )

        assert response.status_code == HTTP_403_FORBIDDEN, (
            f"Path '{caldav_path}' should be rejected but got {response.status_code}"
        )

    @pytest.mark.parametrize(
        "malicious_path",
        [
            "/etc/passwd/",
            "/admin/calendars/user@test.com/uuid/",
            "/../calendars/user@test.com/uuid/",
            "/calendars/",
            "/calendars/user@test.com/",
            "/calendars/victim@test.com/../attacker@test.com/uuid/",
        ],
    )
    def test_create_rejects_malformed_paths(self, malicious_path):
        """Test that malformed CalDAV paths are rejected."""
        user = factories.UserFactory(email="attacker@test.com")
        client = APIClient()
        client.force_login(user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Bad",
                "type": "ical-feed",
                "caldav_path": malicious_path,
            },
            format="json",
        )

        assert response.status_code == HTTP_403_FORBIDDEN, (
            f"Path '{malicious_path}' should be rejected but got {response.status_code}"
        )

    def test_path_traversal_to_other_user_calendar_rejected(self):
        """Test that path traversal to access another user's calendar is blocked."""
        attacker = factories.UserFactory(email="attacker@example.com")
        factories.UserFactory(email="victim@example.com")
        client = APIClient()
        client.force_login(attacker)

        malicious_paths = [
            f"/calendars/{attacker.email}/../victim@example.com/secret-calendar/",
            "/calendars/victim@example.com/secret-calendar/",
        ]

        for path in malicious_paths:
            response = client.post(
                CHANNELS_URL,
                {
                    "name": "Bad",
                    "type": "ical-feed",
                    "caldav_path": path,
                },
                format="json",
            )
            assert response.status_code == HTTP_403_FORBIDDEN, (
                f"Attacker should not access victim's calendar via '{path}'"
            )

    def test_valid_uuid_path_accepted(self):
        """Test that valid UUID-style calendar IDs are accepted."""
        user = factories.UserFactory()
        caldav_path = (
            f"/calendars/users/{user.email}/550e8400-e29b-41d4-a716-446655440000/"
        )
        client = APIClient()
        client.force_login(user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Good",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED

    def test_valid_alphanumeric_path_accepted(self):
        """Test that valid alphanumeric calendar IDs are accepted."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/users/{user.email}/my-calendar-2024/"
        client = APIClient()
        client.force_login(user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Good",
                "type": "ical-feed",
                "caldav_path": caldav_path,
            },
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED
