"""Tests for deleting a MAILBOX-owned calendar (issue #72).

Unlike a plain CalDAV DELETE — which only ever removes the caller's
own share of a mailbox calendar — ``DELETE /api/v1.0/setup/`` reaches
the real owner-branch delete via the internal API, so the calendar
disappears for every mailbox user.
"""

from unittest import mock

from django.test import override_settings

import pytest
from rest_framework.status import (
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
)
from rest_framework.test import APIClient

from core import factories
from core.entitlements.factory import get_entitlements_backend

_SETTINGS = {
    "ENTITLEMENTS_BACKEND": "core.entitlements.backends.local.LocalEntitlementsBackend",
    "ENTITLEMENTS_BACKEND_PARAMETERS": {},
    "CALDAV_INTERNAL_API_KEY": "test-internal-key",
    "FEATURE_MESSAGES_INTEGRATION": True,
    "MESSAGES_API_URL": "http://messages.example",
    "MESSAGES_API_KEY": "test-messages-key",
}


def _authed_client():
    org = factories.OrganizationFactory(external_id="test-org")
    user = factories.UserFactory(organization=org)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
@override_settings(**_SETTINGS)
def test_delete_mailbox_calendar_requires_auth():
    """DELETE /setup/ requires authentication."""
    get_entitlements_backend.cache_clear()
    client = APIClient()
    response = client.delete(
        "/api/v1.0/setup/",
        {"mailbox_email": "contact@co.example", "calendar_uri": "default"},
        format="json",
    )
    assert response.status_code == HTTP_401_UNAUTHORIZED
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(**_SETTINGS)
def test_delete_mailbox_calendar_missing_params():
    """Both mailbox_email and calendar_uri are required."""
    get_entitlements_backend.cache_clear()
    client, _user = _authed_client()

    response = client.delete("/api/v1.0/setup/", {}, format="json")

    assert response.status_code == HTTP_400_BAD_REQUEST
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(**_SETTINGS)
def test_delete_mailbox_calendar_requires_send_role():
    """A viewer-role user cannot delete the mailbox's calendar."""
    get_entitlements_backend.cache_clear()
    client, _user = _authed_client()

    with (
        mock.patch("core.services.setup_service.MessagesService") as mock_messages_cls,
        mock.patch(
            "core.services.caldav_service.requests.Session.request"
        ) as mock_request,
    ):
        mock_messages_cls.return_value.get_user_mailboxes.return_value = [
            {"email": "contact@co.example", "role": "viewer", "users": []}
        ]

        response = client.delete(
            "/api/v1.0/setup/",
            {"mailbox_email": "contact@co.example", "calendar_uri": "default"},
            format="json",
        )

    assert response.status_code == HTTP_400_BAD_REQUEST
    assert "sender" in response.json()["error"]
    mock_request.assert_not_called()
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(**_SETTINGS)
def test_delete_mailbox_calendar_no_access_to_mailbox():
    """A user with no role at all on the mailbox is rejected."""
    get_entitlements_backend.cache_clear()
    client, _user = _authed_client()

    with (
        mock.patch("core.services.setup_service.MessagesService") as mock_messages_cls,
        mock.patch(
            "core.services.caldav_service.requests.Session.request"
        ) as mock_request,
    ):
        mock_messages_cls.return_value.get_user_mailboxes.return_value = []

        response = client.delete(
            "/api/v1.0/setup/",
            {"mailbox_email": "contact@co.example", "calendar_uri": "default"},
            format="json",
        )

    assert response.status_code == HTTP_400_BAD_REQUEST
    mock_request.assert_not_called()
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(**_SETTINGS)
def test_delete_mailbox_calendar_success():
    """A sender-role user can delete the mailbox's calendar for everyone."""
    get_entitlements_backend.cache_clear()
    client, _user = _authed_client()

    with (
        mock.patch("core.services.setup_service.MessagesService") as mock_messages_cls,
        mock.patch(
            "core.services.caldav_service.requests.Session.request"
        ) as mock_request,
    ):
        mock_messages_cls.return_value.get_user_mailboxes.return_value = [
            {"email": "contact@co.example", "role": "admin", "users": []}
        ]
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"deleted": True}
        mock_response.text = '{"deleted": true}'
        mock_request.return_value = mock_response

        response = client.delete(
            "/api/v1.0/setup/",
            {"mailbox_email": "contact@co.example", "calendar_uri": "some-uuid"},
            format="json",
        )

    assert response.status_code == HTTP_204_NO_CONTENT

    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    url = call_kwargs.kwargs.get("url", "") or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else ""
    )
    assert "internal-api/calendars/some-uuid" in url
    method = call_kwargs.kwargs.get("method") or (
        call_kwargs.args[0] if call_kwargs.args else ""
    )
    assert method == "DELETE"
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(**_SETTINGS)
def test_delete_mailbox_calendar_not_found():
    """A 404 from the internal API surfaces as a rejected request, not a 500."""
    get_entitlements_backend.cache_clear()
    client, _user = _authed_client()

    with (
        mock.patch("core.services.setup_service.MessagesService") as mock_messages_cls,
        mock.patch(
            "core.services.caldav_service.requests.Session.request"
        ) as mock_request,
    ):
        mock_messages_cls.return_value.get_user_mailboxes.return_value = [
            {"email": "contact@co.example", "role": "admin", "users": []}
        ]
        mock_response = mock.Mock()
        mock_response.status_code = 404
        mock_response.text = '{"error": "Calendar not found"}'
        mock_request.return_value = mock_response

        response = client.delete(
            "/api/v1.0/setup/",
            {"mailbox_email": "contact@co.example", "calendar_uri": "missing"},
            format="json",
        )

    assert response.status_code == HTTP_400_BAD_REQUEST
    assert "not found" in response.json()["error"]
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(**_SETTINGS)
def test_delete_mailbox_calendar_ownership_mismatch():
    """A 403 (calendar belongs to a different mailbox) is surfaced, not a 500."""
    get_entitlements_backend.cache_clear()
    client, _user = _authed_client()

    with (
        mock.patch("core.services.setup_service.MessagesService") as mock_messages_cls,
        mock.patch(
            "core.services.caldav_service.requests.Session.request"
        ) as mock_request,
    ):
        mock_messages_cls.return_value.get_user_mailboxes.return_value = [
            {"email": "contact@co.example", "role": "admin", "users": []}
        ]
        mock_response = mock.Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": "Calendar does not belong to the given mailbox"
        }
        mock_response.text = (
            '{"error": "Calendar does not belong to the given mailbox"}'
        )
        mock_request.return_value = mock_response

        response = client.delete(
            "/api/v1.0/setup/",
            {"mailbox_email": "contact@co.example", "calendar_uri": "someone-elses"},
            format="json",
        )

    assert response.status_code == HTTP_400_BAD_REQUEST
    assert "does not belong" in response.json()["error"]
    get_entitlements_backend.cache_clear()
