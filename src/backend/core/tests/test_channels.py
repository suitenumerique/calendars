"""Tests for the Channel model and API."""

# pylint: disable=redefined-outer-name,missing-function-docstring,no-member

import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError

import pytest
from rest_framework.test import APIClient

from core import factories, models

pytestmark = pytest.mark.django_db

CHANNELS_URL = "/api/v1.0/channels/"


@pytest.fixture
def authenticated_client():
    """Return an (APIClient, User) pair with forced authentication."""
    user = factories.UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestChannelModel:
    """Tests for the Channel model."""

    def test_verify_token(self):
        channel = factories.ChannelFactory()
        token = channel.encrypted_settings["token"]

        assert channel.verify_token(token)
        assert not channel.verify_token("wrong-token")

    def test_scope_validation_requires_at_least_one(self):
        """Channel with no scope should fail validation."""
        channel = models.Channel(name="no-scope")
        with pytest.raises(ValidationError):
            channel.full_clean()

    def test_role_property(self):
        """Role is stored in settings and accessible via property."""
        user = factories.UserFactory()
        channel = models.Channel(
            name="test",
            user=user,
            settings={"role": "editor"},
        )
        assert channel.role == "editor"

        channel.role = "admin"
        assert channel.settings["role"] == "admin"

    def test_role_default(self):
        """Role defaults to reader when not set."""
        user = factories.UserFactory()
        channel = models.Channel(name="test", user=user)
        assert channel.role == "reader"


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


class TestChannelAPI:
    """Tests for the Channel CRUD API."""

    def test_create_channel(self, authenticated_client):
        client, user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {"name": "My Channel"},
            format="json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My Channel"
        assert "token" in data  # token revealed on creation
        assert len(data["token"]) >= 20
        assert data["role"] == "reader"
        assert data["user"] == str(user.pk)

    def test_create_channel_with_caldav_path(self, authenticated_client):
        client, user = authenticated_client
        caldav_path = f"/calendars/users/{user.email}/my-cal/"
        response = client.post(
            CHANNELS_URL,
            {"name": "Cal Channel", "caldav_path": caldav_path},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["caldav_path"] == caldav_path

    def test_create_channel_wrong_caldav_path(self, authenticated_client):
        client, _user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Bad",
                "caldav_path": "/calendars/users/other@example.com/cal/",
            },
            format="json",
        )
        assert response.status_code == 403

    def test_list_channels(self, authenticated_client):
        client, _user = authenticated_client
        # Create 2 channels
        for i in range(2):
            client.post(
                CHANNELS_URL,
                {"name": f"Channel {i}"},
                format="json",
            )

        response = client.get(CHANNELS_URL)
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_channels_only_own(self, authenticated_client):
        """Users should only see their own channels."""
        client, _user = authenticated_client
        # Create a channel for another user
        factories.ChannelFactory()

        response = client.get(CHANNELS_URL)
        assert response.status_code == 200
        assert len(response.json()) == 0

    def test_retrieve_channel(self, authenticated_client):
        client, _user = authenticated_client
        create_resp = client.post(
            CHANNELS_URL,
            {"name": "Retrieve Me"},
            format="json",
        )
        channel_id = create_resp.json()["id"]

        response = client.get(f"{CHANNELS_URL}{channel_id}/")
        assert response.status_code == 200
        assert response.json()["name"] == "Retrieve Me"
        assert "token" not in response.json()  # token NOT in retrieve

    def test_delete_channel(self, authenticated_client):
        client, _user = authenticated_client
        create_resp = client.post(
            CHANNELS_URL,
            {"name": "Delete Me"},
            format="json",
        )
        channel_id = create_resp.json()["id"]

        response = client.delete(f"{CHANNELS_URL}{channel_id}/")
        assert response.status_code == 204
        assert not models.Channel.objects.filter(pk=channel_id).exists()

    def test_regenerate_token(self, authenticated_client):
        client, _user = authenticated_client
        create_resp = client.post(
            CHANNELS_URL,
            {"name": "Regen"},
            format="json",
        )
        old_token = create_resp.json()["token"]
        channel_id = create_resp.json()["id"]

        response = client.post(f"{CHANNELS_URL}{channel_id}/regenerate-token/")
        assert response.status_code == 200
        new_token = response.json()["token"]
        assert new_token != old_token
        assert len(new_token) >= 20

    def test_unauthenticated(self):
        client = APIClient()
        response = client.get(CHANNELS_URL)
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# CalDAV proxy channel auth tests
# ---------------------------------------------------------------------------


class TestCalDAVProxyChannelAuth:
    """Tests for channel token authentication in the CalDAV proxy."""

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_channel_token_auth_propfind(self, mock_http_cls):
        """A reader channel token should allow PROPFIND."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "reader"},
        )
        token = channel.encrypted_settings["token"]

        mock_response = type(
            "R",
            (),
            {
                "status_code": 207,
                "content": b"<xml/>",
                "headers": {"Content-Type": "application/xml"},
            },
        )()
        mock_http_cls.build_base_headers.return_value = {
            "X-Api-Key": "test",
            "X-Forwarded-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request", return_value=mock_response
        ):
            response = client.generic(
                "PROPFIND",
                f"/caldav/calendars/users/{user.email}/",
                HTTP_X_CHANNEL_ID=str(channel.pk),
                HTTP_X_CHANNEL_TOKEN=token,
                HTTP_DEPTH="1",
            )
        assert response.status_code == 207

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_channel_token_reader_cannot_put(self, _mock_http_cls):
        """A reader channel should NOT allow PUT."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "reader"},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.put(
            f"/caldav/calendars/users/{user.email}/cal/event.ics",
            data=b"BEGIN:VCALENDAR",
            content_type="text/calendar",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
        )
        assert response.status_code == 403

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_channel_token_editor_can_put(self, mock_http_cls):
        """An editor channel should allow PUT."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "editor"},
        )
        token = channel.encrypted_settings["token"]

        mock_response = type(
            "R",
            (),
            {
                "status_code": 201,
                "content": b"",
                "headers": {"Content-Type": "text/plain"},
            },
        )()
        mock_http_cls.build_base_headers.return_value = {
            "X-Api-Key": "test",
            "X-Forwarded-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request", return_value=mock_response
        ):
            response = client.put(
                f"/caldav/calendars/users/{user.email}/cal/event.ics",
                data=b"BEGIN:VCALENDAR",
                content_type="text/calendar",
                HTTP_X_CHANNEL_ID=str(channel.pk),
                HTTP_X_CHANNEL_TOKEN=token,
            )
        assert response.status_code == 201

    def test_channel_token_wrong_path(self):
        """Channel should not access paths outside its user scope."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "reader"},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/users/other@example.com/cal/",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
        )
        assert response.status_code == 403

    def test_invalid_token(self):
        """Invalid token should return 401."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "reader"},
        )

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN="invalid-token-12345",
        )
        assert response.status_code == 401

    def test_missing_channel_id(self):
        """Token without channel ID should return 401."""
        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
            HTTP_X_CHANNEL_TOKEN="some-token",
        )
        assert response.status_code == 401

    def test_nonexistent_channel_id(self):
        """Non-existent channel ID should return 401."""
        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
            HTTP_X_CHANNEL_ID=str(uuid.uuid4()),
            HTTP_X_CHANNEL_TOKEN="some-token",
        )
        assert response.status_code == 401

    def test_inactive_channel_id(self):
        """Inactive channel should return 401."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "reader"},
            is_active=False,
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
        )
        assert response.status_code == 401

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_caldav_path_scoped_channel(self, mock_http_cls):
        """Channel with caldav_path scope restricts to that path."""
        user = factories.UserFactory()
        scoped_path = f"/calendars/users/{user.email}/specific-cal/"
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "reader"},
            caldav_path=scoped_path,
        )
        token = channel.encrypted_settings["token"]

        mock_response = type(
            "R",
            (),
            {
                "status_code": 207,
                "content": b"<xml/>",
                "headers": {"Content-Type": "application/xml"},
            },
        )()
        mock_http_cls.build_base_headers.return_value = {
            "X-Api-Key": "test",
            "X-Forwarded-User": user.email,
        }

        client = APIClient()

        # Allowed: within scoped path
        with patch(
            "core.api.viewsets_caldav.requests.request", return_value=mock_response
        ):
            response = client.generic(
                "PROPFIND",
                f"/caldav{scoped_path}",
                HTTP_X_CHANNEL_ID=str(channel.pk),
                HTTP_X_CHANNEL_TOKEN=token,
                HTTP_DEPTH="1",
            )
        assert response.status_code == 207

        # Denied: different calendar
        response = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/other-cal/",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
        )
        assert response.status_code == 403

    def test_caldav_path_boundary_no_prefix_leak(self):
        """Scoped path /cal1/ must NOT match /cal1-secret/ (trailing slash boundary)."""
        user = factories.UserFactory()
        scoped_path = f"/calendars/users/{user.email}/cal1/"
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "reader"},
            caldav_path=scoped_path,
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/cal1-secret/",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
        )
        assert response.status_code == 403

    @patch("core.api.viewsets_caldav.get_user_entitlements")
    def test_channel_mkcalendar_checks_entitlements(self, mock_entitlements):
        """MKCALENDAR via channel token must still check entitlements."""
        mock_entitlements.return_value = {"can_access": False}

        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"role": "admin"},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "MKCALENDAR",
            f"/caldav/calendars/users/{user.email}/new-cal/",
            HTTP_X_CHANNEL_ID=str(channel.pk),
            HTTP_X_CHANNEL_TOKEN=token,
        )
        assert response.status_code == 403
        mock_entitlements.assert_called_once_with(user.sub, user.email)
