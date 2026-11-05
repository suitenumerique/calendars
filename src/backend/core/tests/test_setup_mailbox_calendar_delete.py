"""Tests for the delete of a mailbox calendar for every mailbox user."""

from unittest import mock

from django.core.cache import cache
from django.test import override_settings

import pytest
from rest_framework.status import (
    HTTP_204_NO_CONTENT,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from rest_framework.test import APIClient

from core import factories
from core.entitlements.factory import get_entitlements_backend
from core.models import Organization

pytestmark = pytest.mark.django_db

_SETTINGS = {
    "ENTITLEMENTS_BACKEND": "core.entitlements.backends.local.LocalEntitlementsBackend",
    "ENTITLEMENTS_BACKEND_PARAMETERS": {},
    "CALDAV_INTERNAL_API_KEY": "test-internal-key",
    "FEATURE_MESSAGES_INTEGRATION": True,
    "MESSAGES_API_URL": "http://messages.example",
    "MESSAGES_API_KEY": "test-messages-key",
    "MESSAGES_CHANNEL_ID": "test-channel",
}

MAILBOX = "contact@co.example"
URL = f"/api/v1.0/calendars/mailboxes/{MAILBOX}/some-uuid/"


@pytest.fixture(autouse=True)
def _settings():
    """Enable the Messages integration and the local entitlements."""
    get_entitlements_backend.cache_clear()
    with override_settings(**_SETTINGS):
        yield
    get_entitlements_backend.cache_clear()


@pytest.fixture(name="client")
def fixture_client():
    """Return an API client logged in as a user of an organization."""
    org = factories.OrganizationFactory(external_id="test-org")
    user = factories.UserFactory(organization=org)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _delete(client, mailboxes, caldav_status=200, url=URL):
    """Send the DELETE with mocked Messages and CalDAV responses."""
    with (
        mock.patch("core.services.setup_service.MessagesService") as mock_messages_cls,
        mock.patch(
            "core.services.caldav_service.requests.Session.request"
        ) as mock_request,
    ):
        mock_messages_cls.return_value.get_user_mailboxes.return_value = mailboxes
        mock_request.return_value = mock.Mock(status_code=caldav_status, text="")
        response = client.delete(url)
    return response, mock_request


def test_delete_mailbox_calendar_requires_auth():
    """The endpoint requires authentication."""
    response = APIClient().delete(URL)

    assert response.status_code == HTTP_401_UNAUTHORIZED


def test_delete_mailbox_calendar_requires_entitlement(client):
    """A user without the can_access entitlement gets a 403."""
    with mock.patch(
        "core.api.permissions.get_user_entitlements",
        return_value={"can_access": False, "can_admin": False},
    ):
        response, mock_request = _delete(
            client, [{"email": MAILBOX, "role": "admin", "users": []}]
        )

    assert response.status_code == HTTP_403_FORBIDDEN
    mock_request.assert_not_called()


def test_delete_mailbox_calendar_no_access_to_mailbox(client):
    """A user with no role on the mailbox gets a 403."""
    response, mock_request = _delete(client, [])

    assert response.status_code == HTTP_403_FORBIDDEN
    assert response.json()["code"] == "mailbox_access_denied"
    mock_request.assert_not_called()


@pytest.mark.parametrize("role", ["viewer", "editor", "sender"])
def test_delete_mailbox_calendar_requires_admin_role(client, role):
    """Only an admin of the mailbox can delete its calendars."""
    response, mock_request = _delete(
        client, [{"email": MAILBOX, "role": role, "users": []}]
    )

    assert response.status_code == HTTP_403_FORBIDDEN
    assert response.json()["code"] == "mailbox_admin_required"
    mock_request.assert_not_called()


def test_delete_mailbox_calendar_ignores_a_cached_admin_role():
    """A demoted admin cannot delete while the cache still says admin."""
    org = factories.OrganizationFactory(external_id="test-org")
    user = factories.UserFactory(organization=org)
    client = APIClient()
    client.force_authenticate(user=user)
    cache.set(
        f"messages:by_user:{user.email}",
        [{"email": MAILBOX, "role": "admin", "users": []}],
    )
    messages_response = mock.Mock(status_code=200)
    messages_response.json.return_value = {
        "results": [{"email": MAILBOX, "role": "viewer", "users": []}]
    }

    with (
        mock.patch(
            "core.services.messages_service.requests.request",
            return_value=messages_response,
        ),
        mock.patch(
            "core.services.caldav_service.requests.Session.request"
        ) as mock_caldav,
    ):
        response = client.delete(URL)

    assert response.status_code == HTTP_403_FORBIDDEN
    assert response.json()["code"] == "mailbox_admin_required"
    mock_caldav.assert_not_called()


def test_delete_mailbox_calendar_success(client):
    """An admin deletes the calendar through the internal API."""
    response, mock_request = _delete(
        client, [{"email": MAILBOX, "role": "admin", "users": []}]
    )

    assert response.status_code == HTTP_204_NO_CONTENT
    mock_request.assert_called_once()
    kwargs = mock_request.call_args.kwargs
    assert kwargs["method"] == "DELETE"
    assert kwargs["url"].endswith("internal-api/calendars/some-uuid")
    assert b'"mailbox_email": "contact@co.example"' in kwargs["data"]


def test_delete_mailbox_calendar_sends_the_mailbox_org(client):
    """The internal API gets the organization of the mailbox.

    The admin is in the "test-org" organization. The mailbox domain gives
    a different organization.
    """
    response, mock_request = _delete(
        client, [{"email": MAILBOX, "role": "admin", "users": []}]
    )

    assert response.status_code == HTTP_204_NO_CONTENT
    mailbox_org = Organization.objects.get(external_id="co.example")
    headers = mock_request.call_args.kwargs["headers"]
    assert headers["X-LS-Org-Id"] == str(mailbox_org.id)
    user_org = Organization.objects.get(external_id="test-org")
    assert headers["X-LS-Org-Id"] != str(user_org.id)


@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="siret")
def test_delete_mailbox_calendar_sends_the_claim_org(client):
    """With an organization claim, the org comes from the mail domain."""
    mailbox_org = factories.OrganizationFactory(external_id="12345678900011")
    response, mock_request = _delete(
        client,
        [
            {
                "email": MAILBOX,
                "role": "admin",
                "users": [],
                "maildomain_custom_attributes": {"siret": "12345678900011"},
            }
        ],
    )

    assert response.status_code == HTTP_204_NO_CONTENT
    headers = mock_request.call_args.kwargs["headers"]
    assert headers["X-LS-Org-Id"] == str(mailbox_org.id)


def test_delete_mailbox_calendar_quotes_the_uri(client):
    """The calendar URI cannot change the internal API URL."""
    response, mock_request = _delete(
        client,
        [{"email": MAILBOX, "role": "admin", "users": []}],
        url=f"/api/v1.0/calendars/mailboxes/{MAILBOX}/a%3Fb%23c/",
    )

    assert response.status_code == HTTP_204_NO_CONTENT
    assert mock_request.call_args.kwargs["url"].endswith(
        "internal-api/calendars/a%3Fb%23c"
    )


@pytest.mark.parametrize("caldav_status", [400, 403, 404])
def test_delete_mailbox_calendar_not_found(client, caldav_status):
    """A calendar that the mailbox does not own gives a 404."""
    response, _ = _delete(
        client,
        [{"email": MAILBOX, "role": "admin", "users": []}],
        caldav_status=caldav_status,
    )

    assert response.status_code == HTTP_404_NOT_FOUND
    assert response.json()["code"] == "calendar_not_found"


def test_delete_mailbox_calendar_caldav_failure(client):
    """A CalDAV server failure gives a 500 without internal details."""
    response, _ = _delete(
        client,
        [{"email": MAILBOX, "role": "admin", "users": []}],
        caldav_status=500,
    )

    assert response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json() == {
        "code": "calendar_deletion_failed",
        "detail": "Calendar deletion failed.",
    }


def test_delete_mailbox_calendar_messages_disabled(client):
    """Without the Messages integration, the endpoint gives a 404."""
    with override_settings(FEATURE_MESSAGES_INTEGRATION=False):
        response, mock_request = _delete(client, [])

    assert response.status_code == HTTP_404_NOT_FOUND
    mock_request.assert_not_called()
