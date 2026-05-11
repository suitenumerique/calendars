"""Tests for the Channel model and API."""

# pylint: disable=redefined-outer-name,missing-function-docstring,no-member,too-many-lines

import base64
import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError

import pytest
import requests as req_lib
from requests.auth import HTTPBasicAuth
from rest_framework.test import APIClient

from core import factories, models
from core.models import uuid_to_urlsafe
from core.services.resource_service import ResourceService

pytestmark = pytest.mark.django_db

CHANNELS_URL = "/api/v1.0/channels/"


def _basic_auth(email, channel_id, token):
    """Build HTTP_AUTHORIZATION header for Basic Auth.

    Format: base64(email:<channel_id><token>). The channel_id is the
    fixed-length base64url-encoded UUID; a UUID instance is converted
    automatically for convenience.
    """
    if isinstance(channel_id, uuid.UUID):
        channel_id = uuid_to_urlsafe(channel_id)
    creds = base64.b64encode(f"{email}:{channel_id}{token}".encode()).decode()
    return f"Basic {creds}"


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

    def test_scope_level_user_requires_user(self):
        with pytest.raises(ValidationError):
            models.Channel(
                name="no-user",
                scope_level="user",
                settings={"scopes": ["calendars:read"]},
            ).full_clean()

    def test_scope_level_calendar_requires_caldav_path(self):
        user = factories.UserFactory()
        with pytest.raises(ValidationError):
            models.Channel(
                name="no-path",
                scope_level="calendar",
                user=user,
                settings={"scopes": ["calendars:read"]},
            ).full_clean()

    def test_scope_level_global_no_fk_required(self):
        channel = models.Channel(
            name="global",
            scope_level="global",
            settings={"scopes": ["calendars:read"]},
        )
        channel.full_clean()

    def test_scopes_property(self):
        user = factories.UserFactory()
        channel = models.Channel(
            name="test",
            user=user,
            settings={"scopes": ["calendars:read", "events:read", "events:write"]},
        )
        assert channel.scopes == ["calendars:read", "events:read", "events:write"]

        channel.scopes = ["calendars:read"]
        assert channel.settings["scopes"] == ["calendars:read"]

    def test_scopes_default(self):
        user = factories.UserFactory()
        channel = models.Channel(name="test", user=user)
        assert not channel.scopes

    def test_allowed_methods_collection(self):
        user = factories.UserFactory()
        channel = models.Channel(
            name="test",
            user=user,
            settings={"scopes": ["calendars:read", "events:read", "events:write"]},
        )
        allowed = channel.allowed_methods(collection=True)
        assert "PROPFIND" in allowed
        assert "PUT" not in allowed
        assert "MKCALENDAR" not in allowed

    def test_allowed_methods_object(self):
        user = factories.UserFactory()
        channel = models.Channel(
            name="test",
            user=user,
            settings={"scopes": ["calendars:read", "events:read", "events:write"]},
        )
        allowed = channel.allowed_methods(collection=False)
        assert "PROPFIND" not in allowed
        assert "GET" in allowed
        assert "PUT" in allowed
        assert "MKCALENDAR" not in allowed

    def test_invalid_scope_rejected(self):
        user = factories.UserFactory()
        with pytest.raises(ValidationError):
            models.Channel(
                name="bad-scope",
                user=user,
                settings={"scopes": ["nonexistent:scope"]},
            ).full_clean()


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


class TestChannelAPI:
    """Tests for the Channel CRUD API."""

    def test_create_channel(self, authenticated_client):
        client, user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {
                "name": "My Channel",
                "type": "caldav",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My Channel"
        assert "token" in data
        assert len(data["token"]) >= 20
        assert "password" in data
        short_id = uuid_to_urlsafe(uuid.UUID(data["id"]))
        assert data["password"] == f"{short_id}{data['token']}"
        assert len(short_id) == 22
        assert data["scopes"] == ["calendars:read", "events:read"]
        assert data["scope_level"] == "user"
        assert data["user"] == str(user.pk)

    def test_create_channel_with_scopes(self, authenticated_client):
        client, _user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Editor Channel",
                "type": "caldav",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read", "events:write"],
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["scopes"] == [
            "calendars:read",
            "events:read",
            "events:write",
        ]

    def test_create_channel_with_caldav_path(self, authenticated_client):
        client, user = authenticated_client
        caldav_path = f"/calendars/users/{user.email}/my-cal/"
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Cal Channel",
                "type": "caldav",
                "caldav_path": caldav_path,
                "scope_level": "calendar",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["caldav_path"] == caldav_path
        assert data["scope_level"] == "calendar"

    def test_create_ical_feed_with_non_calendar_scope_level_fails(
        self, authenticated_client
    ):
        client, user = authenticated_client
        caldav_path = f"/calendars/users/{user.email}/my-cal/"
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Bad",
                "type": "ical-feed",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read"],
                "caldav_path": caldav_path,
            },
            format="json",
        )
        assert response.status_code == 400
        assert any(
            err.get("attr") == "scope_level"
            for err in response.json().get("errors", [])
        )

    def test_create_channel_missing_scope_level_fails(self, authenticated_client):
        client, _user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Bad",
                "type": "caldav",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        assert response.status_code == 400

    def test_create_channel_missing_scopes_fails(self, authenticated_client):
        client, _user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Bad",
                "type": "caldav",
                "scope_level": "user",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_create_calendar_scope_without_path_fails(self, authenticated_client):
        client, _user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Bad",
                "type": "caldav",
                "scope_level": "calendar",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        assert response.status_code == 400

    def test_create_channel_wrong_caldav_path(self, authenticated_client):
        client, _user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Bad",
                "type": "caldav",
                "caldav_path": "/calendars/users/other@example.com/cal/",
                "scope_level": "calendar",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        assert response.status_code == 403

    def test_list_channels(self, authenticated_client):
        client, _user = authenticated_client
        for i in range(2):
            client.post(
                CHANNELS_URL,
                {
                    "name": f"Channel {i}",
                    "type": "caldav",
                    "scope_level": "user",
                    "scopes": ["calendars:read", "events:read"],
                },
                format="json",
            )

        response = client.get(CHANNELS_URL)
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_channels_only_own(self, authenticated_client):
        client, _user = authenticated_client
        factories.ChannelFactory()

        response = client.get(CHANNELS_URL)
        assert response.status_code == 200
        assert len(response.json()) == 0

    def test_retrieve_channel(self, authenticated_client):
        client, _user = authenticated_client
        create_resp = client.post(
            CHANNELS_URL,
            {
                "name": "Retrieve Me",
                "type": "caldav",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        channel_id = create_resp.json()["id"]

        response = client.get(f"{CHANNELS_URL}{channel_id}/")
        assert response.status_code == 200
        assert response.json()["name"] == "Retrieve Me"
        assert "token" not in response.json()

    def test_delete_channel(self, authenticated_client):
        client, _user = authenticated_client
        create_resp = client.post(
            CHANNELS_URL,
            {
                "name": "Delete Me",
                "type": "caldav",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read"],
            },
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
            {
                "name": "Regen",
                "type": "caldav",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        old_token = create_resp.json()["token"]
        channel_id = create_resp.json()["id"]

        response = client.post(f"{CHANNELS_URL}{channel_id}/regenerate-token/")
        assert response.status_code == 200
        new_token = response.json()["token"]
        assert new_token != old_token
        assert len(new_token) >= 20

    def test_delete_channel_by_other_user_forbidden(self):
        user_a = factories.UserFactory()
        client_a = APIClient()
        client_a.force_authenticate(user=user_a)

        create_resp = client_a.post(
            CHANNELS_URL,
            {
                "name": "A's Channel",
                "type": "caldav",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        channel_id = create_resp.json()["id"]

        user_b = factories.UserFactory()
        client_b = APIClient()
        client_b.force_authenticate(user=user_b)

        response = client_b.delete(f"{CHANNELS_URL}{channel_id}/")
        assert response.status_code in (403, 404)
        assert models.Channel.objects.filter(pk=channel_id).exists()

    def test_regenerate_token_by_other_user_forbidden(self):
        user_a = factories.UserFactory()
        client_a = APIClient()
        client_a.force_authenticate(user=user_a)

        create_resp = client_a.post(
            CHANNELS_URL,
            {
                "name": "A's Channel",
                "type": "caldav",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        channel_id = create_resp.json()["id"]

        user_b = factories.UserFactory()
        client_b = APIClient()
        client_b.force_authenticate(user=user_b)

        response = client_b.post(f"{CHANNELS_URL}{channel_id}/regenerate-token/")
        assert response.status_code in (403, 404)

    def test_unauthenticated(self):
        client = APIClient()
        response = client.get(CHANNELS_URL)
        assert response.status_code in (401, 403)

    def test_create_global_channel_via_api_forbidden(self, authenticated_client):
        """Global channels cannot be created via the API."""
        client, _user = authenticated_client
        response = client.post(
            CHANNELS_URL,
            {
                "name": "Global",
                "type": "caldav",
                "scope_level": "global",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        assert response.status_code == 403


class TestChannelTokenBoundary:
    """Verify the API never leaks a channel's stored token.

    The CalDAV password is meant to be returned only on create and
    regenerate. The iCal-feed URL embeds the token in its path, so it
    must not be derivable for non-ical-feed channels — neither directly
    via the ``url`` field nor by mutating the channel's ``type``.
    """

    @staticmethod
    def _create_caldav(client, name="Boundary"):
        return client.post(
            CHANNELS_URL,
            {
                "name": name,
                "type": "caldav",
                "scope_level": "user",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )

    def test_caldav_retrieve_does_not_expose_token(self, authenticated_client):
        client, _user = authenticated_client
        create_resp = self._create_caldav(client)
        stored_token = create_resp.json()["token"]
        channel_id = create_resp.json()["id"]

        body = client.get(f"{CHANNELS_URL}{channel_id}/").json()

        assert body["url"] is None
        assert "token" not in body
        assert "password" not in body
        assert "encrypted_settings" not in body
        # Defense-in-depth: the raw token must not appear anywhere.
        assert stored_token not in str(body)

    def test_caldav_list_does_not_expose_token(self, authenticated_client):
        client, _user = authenticated_client
        create_resp = self._create_caldav(client)
        stored_token = create_resp.json()["token"]

        body = client.get(CHANNELS_URL).json()

        assert stored_token not in str(body)
        for entry in body:
            assert entry["url"] is None
            assert "token" not in entry
            assert "password" not in entry
            assert "encrypted_settings" not in entry

    def test_patch_cannot_flip_caldav_to_ical_feed(self, authenticated_client):
        """PATCH must not let a caller mutate ``type`` and leak the token.

        If ``type`` were mutable, a caller could turn a CalDAV channel
        into an ical-feed and read the token back from the URL field.
        """
        client, _user = authenticated_client
        create_resp = self._create_caldav(client)
        stored_token = create_resp.json()["token"]
        channel_id = create_resp.json()["id"]

        patch_resp = client.patch(
            f"{CHANNELS_URL}{channel_id}/",
            {"type": "ical-feed"},
            format="json",
        )
        assert patch_resp.status_code == 200

        # Type stayed put; URL still hidden.
        get_body = client.get(f"{CHANNELS_URL}{channel_id}/").json()
        assert get_body["type"] == "caldav"
        assert get_body["url"] is None
        assert stored_token not in str(get_body)

        # Direct DB check — the model wasn't mutated either.
        channel = models.Channel.objects.get(pk=channel_id)
        assert channel.type == "caldav"


# ---------------------------------------------------------------------------
# CalDAV proxy channel auth tests
# ---------------------------------------------------------------------------


class TestCalDAVProxyChannelAuth:  # pylint: disable=too-many-public-methods
    """Tests for HTTP Basic Auth channel authentication in the CalDAV proxy."""

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_basic_auth_propfind(self, mock_http_cls):
        """A read-scoped channel should allow PROPFIND."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
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
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.generic(
                "PROPFIND",
                f"/caldav/calendars/users/{user.email}/",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
                HTTP_DEPTH="1",
            )
        assert response.status_code == 207

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_read_scope_cannot_put(self, _mock_http_cls):
        """A read-only channel should NOT allow PUT."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.put(
            f"/caldav/calendars/users/{user.email}/cal/event.ics",
            data=b"BEGIN:VCALENDAR",
            content_type="text/calendar",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_write_scope_can_put(self, mock_http_cls):
        """A channel with events:write should allow PUT."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:read", "events:write"]},
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
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.put(
                f"/caldav/calendars/users/{user.email}/cal/event.ics",
                data=b"BEGIN:VCALENDAR",
                content_type="text/calendar",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
            )
        assert response.status_code == 201

    def test_channel_wrong_path(self):
        """Channel should not access paths outside its user scope."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/users/other@example.com/cal/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_propfind_root_allowed_for_discovery(self, mock_http_cls):
        """Thunderbird/Apple Calendar PROPFIND `/` to find the user principal."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
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
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.generic(
                "PROPFIND",
                "/caldav/",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
                HTTP_DEPTH="0",
            )
        assert response.status_code == 207

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_propfind_own_principal_allowed(self, mock_http_cls):
        """User-scope channel may PROPFIND its own principal URL."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
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
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.generic(
                "PROPFIND",
                f"/caldav/principals/users/{user.email}/",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
                HTTP_DEPTH="0",
            )
        assert response.status_code == 207

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_report_on_calendar_collection_allowed_with_events_read(
        self, mock_http_cls
    ):
        """REPORT on a calendar collection (path ending with `/`) is
        the standard CalDAV way to fetch events (calendar-query,
        calendar-multiget, sync-collection) and must be allowed when
        the channel has events:read."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:read"]},
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
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.generic(
                "REPORT",
                f"/caldav/calendars/users/{user.email}/cal/",
                data=b"<calendar-query/>",
                content_type="application/xml",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
                HTTP_DEPTH="1",
            )
        assert response.status_code == 207

    def test_report_on_calendar_collection_forbidden_without_events_read(self):
        """REPORT on a calendar collection requires events:read."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "REPORT",
            f"/caldav/calendars/users/{user.email}/cal/",
            data=b"<calendar-query/>",
            content_type="application/xml",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_propfind_other_user_principal_forbidden(self):
        """A user-scope channel must not reach another user's principal."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/principals/users/other@example.com/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_invalid_token(self):
        """Invalid token should return 401."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, "invalid-token"),
        )
        assert response.status_code == 401

    def test_missing_auth(self):
        """No auth should return 401."""
        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
        )
        assert response.status_code == 401

    def test_nonexistent_channel_id(self):
        """Non-existent channel ID should return 401."""
        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
            HTTP_AUTHORIZATION=_basic_auth(
                "test@example.com", uuid.uuid4(), "some-token"
            ),
        )
        assert response.status_code == 401

    def test_malformed_uuid_channel_id(self):
        """Malformed UUID as channel ID should return 401, not 500."""
        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
            HTTP_AUTHORIZATION=_basic_auth(
                "test@example.com", "not-a-uuid", "some-token"
            ),
        )
        assert response.status_code == 401

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_short_channel_id(self, mock_http_cls):
        """Base64url-encoded channel ID should authenticate successfully."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]
        short_id = uuid_to_urlsafe(channel.pk)

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
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.generic(
                "PROPFIND",
                f"/caldav/calendars/users/{user.email}/",
                HTTP_AUTHORIZATION=_basic_auth(user.email, short_id, token),
                HTTP_DEPTH="1",
            )
        assert response.status_code == 207

    def test_inactive_channel(self):
        """Inactive channel should return 401."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
            is_active=False,
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 401

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_caldav_path_scoped_channel(self, mock_http_cls):
        """Channel with scope_level=calendar restricts to that path."""
        user = factories.UserFactory()
        scoped_path = f"/calendars/users/{user.email}/specific-cal/"
        channel = factories.ChannelFactory(
            user=user,
            scope_level="calendar",
            settings={"scopes": ["calendars:read"]},
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
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()

        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.generic(
                "PROPFIND",
                f"/caldav{scoped_path}",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
                HTTP_DEPTH="1",
            )
        assert response.status_code == 207

        response = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/other-cal/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_caldav_path_boundary_no_prefix_leak(self):
        """Scoped path /cal1/ must NOT match /cal1-secret/."""
        user = factories.UserFactory()
        scoped_path = f"/calendars/users/{user.email}/cal1/"
        channel = factories.ChannelFactory(
            user=user,
            scope_level="calendar",
            settings={"scopes": ["calendars:read"]},
            caldav_path=scoped_path,
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/cal1-secret/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    @patch("core.api.viewsets_caldav.get_user_entitlements")
    def test_channel_mkcalendar_checks_entitlements(self, mock_entitlements):
        """MKCALENDAR via channel must still check entitlements."""
        mock_entitlements.return_value = {"can_access": False}

        user = factories.UserFactory()
        # calendars:write is global-only — use a global channel that acts
        # on behalf of `user` via path-based user derivation.
        channel = factories.ChannelFactory(
            scope_level="global",
            user=None,
            organization=user.organization,
            settings={
                "scopes": [
                    "calendars:read",
                    "events:write",
                    "calendars:write",
                ]
            },
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "MKCALENDAR",
            f"/caldav/calendars/users/{user.email}/new-cal/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403
        mock_entitlements.assert_called_once_with(user.sub, user.email)

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_global_channel_acting_user_comes_from_basic_auth(self, mock_http_cls):
        """Global channel: the acting user is derived from the Basic
        Auth email, not the path. Using distinct emails proves Basic
        Auth wins — changing the path can't pivot X-LS-User."""
        org = factories.OrganizationFactory()
        path_user = factories.UserFactory(organization=org)
        auth_user = factories.UserFactory(organization=org)
        assert path_user.email != auth_user.email

        channel = factories.ChannelFactory(
            scope_level="global",
            user=None,
            organization=org,
            settings={"scopes": ["calendars:read", "events:read", "events:write"]},
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
            "X-LS-Api-Key": "test",
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.generic(
                "PROPFIND",
                f"/caldav/calendars/users/{path_user.email}/",
                HTTP_AUTHORIZATION=_basic_auth(auth_user.email, channel.pk, token),
                HTTP_DEPTH="1",
            )
        assert response.status_code == 207

        # X-LS-User must come from the Basic Auth email, not the path.
        call_args = mock_http_cls.build_base_headers.call_args
        forwarded_user = call_args.args[0]
        assert forwarded_user.email == auth_user.email
        assert forwarded_user.email != path_user.email

    def test_global_channel_unknown_user_rejected(self):
        """Global channel with unknown user email returns 403."""
        channel = factories.ChannelFactory(
            scope_level="global",
            user=None,
            organization=factories.OrganizationFactory(),
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/users/nobody@nowhere.com/",
            HTTP_AUTHORIZATION=_basic_auth("nobody@nowhere.com", channel.pk, token),
        )
        assert response.status_code == 403

    def test_global_channel_non_user_path_rejected(self):
        """Global channel on a path without a user should fail."""
        channel = factories.ChannelFactory(
            scope_level="global",
            user=None,
            organization=factories.OrganizationFactory(),
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/principals/",
            HTTP_AUTHORIZATION=_basic_auth("test@example.com", channel.pk, token),
        )
        assert response.status_code == 403

    def test_user_channel_email_mismatch_rejected(self):
        """User-scoped channel rejects requests with wrong email."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/",
            HTTP_AUTHORIZATION=_basic_auth("wrong@example.com", channel.pk, token),
        )
        assert response.status_code == 403


class TestChannelScopeSecurity:
    """Security tests for scope-based access control.

    DELETE appears in both events:write and calendars:write. The proxy
    must distinguish between deleting an event (object path like
    /cal/event.ics) and deleting a calendar (collection path like /cal/).
    """

    def test_events_write_cannot_delete_calendar_collection(self):
        """events:write must NOT allow deleting a calendar (collection).

        A channel with only events:write could otherwise escalate to
        calendar deletion since DELETE is in both scope method sets.
        """
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:write"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.delete(
            f"/caldav/calendars/users/{user.email}/my-calendar/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_events_write_can_delete_event_object(self, mock_http_cls):
        """events:write SHOULD allow deleting an event (.ics object)."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:write"]},
        )
        token = channel.encrypted_settings["token"]

        mock_response = type(
            "R",
            (),
            {
                "status_code": 204,
                "content": b"",
                "headers": {"Content-Type": "text/plain"},
            },
        )()
        mock_http_cls.build_base_headers.return_value = {
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.delete(
                f"/caldav/calendars/users/{user.email}/cal/event.ics",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
            )
        assert response.status_code == 204

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_calendars_write_can_delete_calendar(self, mock_http_cls):
        """calendars:write SHOULD allow deleting a calendar."""
        user = factories.UserFactory()
        # calendars:write is global-only — use a global channel that acts
        # on behalf of `user` via path-based user derivation.
        channel = factories.ChannelFactory(
            scope_level="global",
            user=None,
            organization=user.organization,
            settings={
                "scopes": [
                    "calendars:read",
                    "events:read",
                    "calendars:write",
                ]
            },
        )
        token = channel.encrypted_settings["token"]

        mock_response = type(
            "R",
            (),
            {
                "status_code": 204,
                "content": b"",
                "headers": {"Content-Type": "text/plain"},
            },
        )()
        mock_http_cls.build_base_headers.return_value = {
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.delete(
                f"/caldav/calendars/users/{user.email}/my-calendar/",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
            )
        assert response.status_code == 204

    def test_events_write_cannot_proppatch_calendar(self):
        """events:write must NOT allow PROPPATCH on calendars.

        PROPPATCH changes calendar properties (name, color, etc.) and
        requires calendars:write.
        """
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:write"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "PROPPATCH",
            f"/caldav/calendars/users/{user.email}/my-calendar/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_events_write_cannot_mkcalendar(self):
        """events:write must NOT allow MKCALENDAR."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:write"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "MKCALENDAR",
            f"/caldav/calendars/users/{user.email}/new-cal/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_events_read_cannot_put(self):
        """events:read must NOT allow PUT."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.put(
            f"/caldav/calendars/users/{user.email}/cal/event.ics",
            data=b"BEGIN:VCALENDAR",
            content_type="text/calendar",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_events_read_cannot_delete(self):
        """events:read must NOT allow DELETE."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.delete(
            f"/caldav/calendars/users/{user.email}/cal/event.ics",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_calendars_read_cannot_get_event(self):
        """calendars:read (without events:read) must NOT allow GET."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.get(
            f"/caldav/calendars/users/{user.email}/cal/event.ics",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_calendars_read_cannot_report(self):
        """calendars:read (without events:read) must NOT allow REPORT."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read"]},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        response = client.generic(
            "REPORT",
            f"/caldav/calendars/users/{user.email}/cal/",
            HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
        )
        assert response.status_code == 403

    def test_no_scopes_denies_everything(self):
        """A channel with empty scopes should deny all methods."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": []},
        )
        token = channel.encrypted_settings["token"]

        client = APIClient()
        for method in ("PROPFIND", "GET", "PUT", "DELETE"):
            response = client.generic(
                method,
                f"/caldav/calendars/users/{user.email}/cal/event.ics",
                HTTP_AUTHORIZATION=_basic_auth(user.email, channel.pk, token),
            )
            assert response.status_code == 403, (
                f"{method} should be denied with empty scopes"
            )


class TestCalDAVLibraryCompat:
    """Verify the python caldav library's auth works with our proxy."""

    def test_caldav_library_produces_correct_auth_header(self):
        """The header the caldav library sends must be parseable by
        our proxy. This test constructs auth exactly as the library
        does (HTTPBasicAuth) and verifies the proxy accepts it."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:read"]},
        )
        token = channel.encrypted_settings["token"]
        short_id = uuid_to_urlsafe(channel.pk)

        auth = HTTPBasicAuth(user.email, f"{short_id}{token}")
        prepared = req_lib.Request("PROPFIND", "http://testserver/caldav/").prepare()
        auth(prepared)
        header = prepared.headers["Authorization"]

        decoded = base64.b64decode(header.split(" ")[1]).decode()
        email, credentials = decoded.split(":", 1)
        assert email == user.email
        assert credentials[:22] == short_id
        assert credentials[22:] == token

    @patch("core.api.viewsets_caldav.CalDAVHTTPClient")
    def test_caldav_library_auth_accepted_by_proxy(self, mock_http_cls):
        """End-to-end: construct auth the way the caldav library does,
        send it to the proxy, and verify it authenticates."""
        user = factories.UserFactory()
        channel = factories.ChannelFactory(
            user=user,
            settings={"scopes": ["calendars:read", "events:read"]},
        )
        token = channel.encrypted_settings["token"]
        short_id = uuid_to_urlsafe(channel.pk)

        auth = HTTPBasicAuth(user.email, f"{short_id}{token}")
        prepared = req_lib.Request("PROPFIND", "http://testserver/").prepare()
        auth(prepared)
        header = prepared.headers["Authorization"]

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
            "X-LS-Api-Key": "test",
            "X-LS-User": user.email,
        }

        client = APIClient()
        with patch(
            "core.api.viewsets_caldav.requests.request",
            return_value=mock_response,
        ):
            response = client.generic(
                "PROPFIND",
                f"/caldav/calendars/users/{user.email}/",
                HTTP_AUTHORIZATION=header,
                HTTP_DEPTH="1",
            )
        assert response.status_code == 207

    def test_401_includes_www_authenticate_header(self):
        """The 401 response must include WWW-Authenticate so the
        caldav library knows to retry with Basic Auth."""
        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
        )
        assert response.status_code == 401
        assert response["WWW-Authenticate"] == 'Basic realm="CalDAV"'  # pylint: disable=unsubscriptable-object

    def test_401_omits_www_authenticate_for_web_client(self):
        """When the web frontend sends X-LS-Client: web, the 401 must
        NOT carry the Basic challenge — otherwise the browser shows its
        native popup on session expiry. The frontend handles 401 itself
        by redirecting to login."""
        client = APIClient()
        response = client.generic(
            "PROPFIND",
            "/caldav/calendars/",
            HTTP_X_LS_CLIENT="web",
        )
        assert response.status_code == 401
        assert "WWW-Authenticate" not in response


class TestChannelCrossOrgResourceAccess:
    """Channel tokens for cross-org resource calendars should not work."""

    def test_channel_for_cross_org_resource_blocked(self):
        org_a = factories.OrganizationFactory(external_id="chan-org-a")
        user_a = factories.UserFactory(organization=org_a)

        client = APIClient()
        client.force_authenticate(user=user_a)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Cross-org resource channel",
                "type": "caldav",
                "caldav_path": ("/calendars/resources/nonexistent-resource/default/"),
                "scope_level": "calendar",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        assert response.status_code == 403

    @pytest.mark.xdist_group("caldav")
    def test_channel_for_same_org_resource_allowed(self):
        org = factories.OrganizationFactory(external_id="chan-same-org")
        user = factories.UserFactory(organization=org)

        service = ResourceService()
        resource = service.create_resource(user, "Test Room", "ROOM")
        resource_id = resource["id"]

        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            CHANNELS_URL,
            {
                "name": "Same-org resource channel",
                "type": "caldav",
                "caldav_path": (f"/calendars/resources/{resource_id}/default/"),
                "scope_level": "calendar",
                "scopes": ["calendars:read", "events:read"],
            },
            format="json",
        )
        assert response.status_code == 201
