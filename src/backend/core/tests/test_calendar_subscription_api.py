"""Tests for calendar subscription token API."""

from urllib.parse import quote

from django.urls import reverse

import pytest
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from rest_framework.test import APIClient

from core import factories
from core.models import CalendarSubscriptionToken


@pytest.mark.django_db
class TestSubscriptionTokenViewSet:
    """Tests for the new standalone SubscriptionTokenViewSet."""

    def test_create_subscription_token(self):
        """Test creating a subscription token for a calendar."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/{user.email}/test-calendar-uuid/"
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {
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
        assert response.data["calendar_name"] == "My Test Calendar"

        # Verify token was created in database
        assert CalendarSubscriptionToken.objects.filter(
            owner=user, caldav_path=caldav_path
        ).exists()

    def test_create_subscription_token_normalizes_path(self):
        """Test that caldav_path is normalized to have leading/trailing slashes."""
        user = factories.UserFactory()
        caldav_path = f"calendars/{user.email}/test-uuid"  # No leading/trailing slash
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {"caldav_path": caldav_path},
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED
        # Path should be normalized
        assert response.data["caldav_path"] == f"/calendars/{user.email}/test-uuid/"

    def test_create_subscription_token_returns_existing(self):
        """Test that creating a token when one exists returns the existing one."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()
        client.force_login(subscription.owner)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {
                "caldav_path": subscription.caldav_path,
                "calendar_name": "Updated Name",
            },
            format="json",
        )

        assert response.status_code == HTTP_200_OK
        assert response.data["token"] == str(subscription.token)
        # Name should be updated
        subscription.refresh_from_db()
        assert subscription.calendar_name == "Updated Name"

    def test_get_subscription_token_by_path(self):
        """Test retrieving an existing subscription token by CalDAV path."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()
        client.force_login(subscription.owner)

        url = reverse("subscription-tokens-by-path")
        response = client.get(url, {"caldav_path": subscription.caldav_path})

        assert response.status_code == HTTP_200_OK
        assert response.data["token"] == str(subscription.token)
        assert "url" in response.data

    def test_get_subscription_token_not_found(self):
        """Test retrieving token when none exists."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/{user.email}/nonexistent/"
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-by-path")
        response = client.get(url, {"caldav_path": caldav_path})

        assert response.status_code == HTTP_404_NOT_FOUND

    def test_get_subscription_token_missing_path(self):
        """Test that missing caldav_path query param returns 400."""
        user = factories.UserFactory()
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-by-path")
        response = client.get(url)

        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_delete_subscription_token(self):
        """Test revoking a subscription token."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()
        client.force_login(subscription.owner)

        base_url = reverse("subscription-tokens-by-path")
        url = f"{base_url}?caldav_path={quote(subscription.caldav_path, safe='')}"
        response = client.delete(url)

        assert response.status_code == HTTP_204_NO_CONTENT
        assert not CalendarSubscriptionToken.objects.filter(pk=subscription.pk).exists()

    def test_delete_subscription_token_not_found(self):
        """Test deleting token when none exists."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/{user.email}/nonexistent/"
        client = APIClient()
        client.force_login(user)

        base_url = reverse("subscription-tokens-by-path")
        url = f"{base_url}?caldav_path={quote(caldav_path, safe='')}"
        response = client.delete(url)

        assert response.status_code == HTTP_404_NOT_FOUND

    def test_non_owner_cannot_create_token(self):
        """Test that users cannot create tokens for other users' calendars."""
        user = factories.UserFactory()
        other_user = factories.UserFactory()
        caldav_path = f"/calendars/{other_user.email}/test-calendar/"
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {"caldav_path": caldav_path},
            format="json",
        )

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_non_owner_cannot_get_token(self):
        """Test that users cannot get tokens for other users' calendars."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        other_user = factories.UserFactory()
        client = APIClient()
        client.force_login(other_user)

        url = reverse("subscription-tokens-by-path")
        response = client.get(url, {"caldav_path": subscription.caldav_path})

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_non_owner_cannot_delete_token(self):
        """Test that users cannot delete tokens for other users' calendars."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        other_user = factories.UserFactory()
        client = APIClient()
        client.force_login(other_user)

        base_url = reverse("subscription-tokens-by-path")
        url = f"{base_url}?caldav_path={quote(subscription.caldav_path, safe='')}"
        response = client.delete(url)

        assert response.status_code == HTTP_403_FORBIDDEN
        # Token should still exist
        assert CalendarSubscriptionToken.objects.filter(pk=subscription.pk).exists()

    def test_unauthenticated_cannot_create_token(self):
        """Test that unauthenticated users cannot create tokens."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/{user.email}/test-calendar/"
        client = APIClient()

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {"caldav_path": caldav_path},
            format="json",
        )

        assert response.status_code == HTTP_401_UNAUTHORIZED

    def test_unauthenticated_cannot_get_token(self):
        """Test that unauthenticated users cannot get tokens."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        client = APIClient()

        url = reverse("subscription-tokens-by-path")
        response = client.get(url, {"caldav_path": subscription.caldav_path})

        assert response.status_code == HTTP_401_UNAUTHORIZED

    def test_regenerate_token(self):
        """Test regenerating a token by delete + create."""
        subscription = factories.CalendarSubscriptionTokenFactory()
        old_token = subscription.token
        client = APIClient()
        client.force_login(subscription.owner)

        base_by_path_url = reverse("subscription-tokens-by-path")
        by_path_url = f"{base_by_path_url}?caldav_path={quote(subscription.caldav_path, safe='')}"
        create_url = reverse("subscription-tokens-list")

        # Delete old token
        response = client.delete(by_path_url)
        assert response.status_code == HTTP_204_NO_CONTENT

        # Create new token
        response = client.post(
            create_url,
            {"caldav_path": subscription.caldav_path},
            format="json",
        )
        assert response.status_code == HTTP_201_CREATED
        assert response.data["token"] != str(old_token)

    def test_unique_constraint_per_owner_calendar(self):
        """Test that only one token can exist per owner+caldav_path."""
        subscription = factories.CalendarSubscriptionTokenFactory()

        # Try to create another token for the same path - should return existing
        client = APIClient()
        client.force_login(subscription.owner)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {"caldav_path": subscription.caldav_path},
            format="json",
        )

        # Should return the existing token, not create a new one
        assert response.status_code == HTTP_200_OK
        assert response.data["token"] == str(subscription.token)
        assert (
            CalendarSubscriptionToken.objects.filter(owner=subscription.owner).count()
            == 1
        )


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
            # Path traversal attacks
            "../other-calendar/",
            "../../etc/passwd/",
            "..%2F..%2Fetc%2Fpasswd/",  # URL-encoded traversal
            # Query parameter injection
            "uuid?export=true/",
            "uuid?admin=true/",
            # Fragment injection
            "uuid#malicious/",
            # Special characters that shouldn't be in calendar IDs
            "uuid;rm -rf/",
            "uuid|cat /etc/passwd/",
            "uuid$(whoami)/",
            "uuid`whoami`/",
            # Double slashes
            "uuid//",
            "/uuid/",
            # Spaces and other whitespace
            "uuid with spaces/",
            "uuid\ttab/",
            # Unicode tricks
            "uuid\u002e\u002e/",  # Unicode dots
        ],
    )
    def test_create_token_rejects_malicious_calendar_id(self, malicious_suffix):
        """Test that malicious calendar IDs in paths are rejected."""
        user = factories.UserFactory()
        caldav_path = f"/calendars/{user.email}/{malicious_suffix}"
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {"caldav_path": caldav_path},
            format="json",
        )

        # Should be rejected - either 403 (invalid format) or path doesn't normalize
        assert response.status_code == HTTP_403_FORBIDDEN, (
            f"Path '{caldav_path}' should be rejected but got {response.status_code}"
        )

    @pytest.mark.parametrize(
        "malicious_path",
        [
            # Completely wrong structure
            "/etc/passwd/",
            "/admin/calendars/user@test.com/uuid/",
            "/../calendars/user@test.com/uuid/",
            # Missing segments
            "/calendars/",
            "/calendars/user@test.com/",
            # Path traversal to access another user's calendar
            "/calendars/victim@test.com/../attacker@test.com/uuid/",
        ],
    )
    def test_create_token_rejects_malformed_paths(self, malicious_path):
        """Test that malformed CalDAV paths are rejected."""
        user = factories.UserFactory(email="attacker@test.com")
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {"caldav_path": malicious_path},
            format="json",
        )

        # Should be rejected
        assert response.status_code == HTTP_403_FORBIDDEN, (
            f"Path '{malicious_path}' should be rejected but got {response.status_code}"
        )

    def test_path_traversal_to_other_user_calendar_rejected(self):
        """Test that path traversal to access another user's calendar is blocked."""
        attacker = factories.UserFactory(email="attacker@example.com")
        victim = factories.UserFactory(email="victim@example.com")
        client = APIClient()
        client.force_login(attacker)

        # Try to access victim's calendar via path traversal
        malicious_paths = [
            f"/calendars/{attacker.email}/../{victim.email}/secret-calendar/",
            f"/calendars/{victim.email}/secret-calendar/",  # Direct access
        ]

        url = reverse("subscription-tokens-list")
        for path in malicious_paths:
            response = client.post(
                url,
                {"caldav_path": path},
                format="json",
            )
            assert response.status_code == HTTP_403_FORBIDDEN, (
                f"Attacker should not access victim's calendar via '{path}'"
            )

    def test_valid_uuid_path_accepted(self):
        """Test that valid UUID-style calendar IDs are accepted."""
        user = factories.UserFactory()
        # Standard UUID format
        caldav_path = f"/calendars/{user.email}/550e8400-e29b-41d4-a716-446655440000/"
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {"caldav_path": caldav_path},
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED

    def test_valid_alphanumeric_path_accepted(self):
        """Test that valid alphanumeric calendar IDs are accepted."""
        user = factories.UserFactory()
        # Alphanumeric with hyphens (allowed by regex)
        caldav_path = f"/calendars/{user.email}/my-calendar-2024/"
        client = APIClient()
        client.force_login(user)

        url = reverse("subscription-tokens-list")
        response = client.post(
            url,
            {"caldav_path": caldav_path},
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED

    def test_get_token_with_malicious_path_rejected(self):
        """Test that GET requests with malicious paths are rejected."""
        user = factories.UserFactory()
        client = APIClient()
        client.force_login(user)

        malicious_path = f"/calendars/{user.email}/../../../etc/passwd/"

        url = reverse("subscription-tokens-by-path")
        response = client.get(url, {"caldav_path": malicious_path})

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_delete_token_with_malicious_path_rejected(self):
        """Test that DELETE requests with malicious paths are rejected."""
        user = factories.UserFactory()
        client = APIClient()
        client.force_login(user)

        malicious_path = f"/calendars/{user.email}/../../../etc/passwd/"

        base_url = reverse("subscription-tokens-by-path")
        url = f"{base_url}?caldav_path={quote(malicious_path, safe='')}"
        response = client.delete(url)

        assert response.status_code == HTTP_403_FORBIDDEN
