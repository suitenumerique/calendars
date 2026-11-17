"""Tests for the calendar setup API errors."""

from unittest import mock

from django.test import override_settings

import pytest
import requests
from rest_framework.test import APIClient

from core import factories

pytestmark = pytest.mark.django_db

SETUP_URL = "/api/v1.0/setup/"


def _client_for(user):
    client = APIClient()
    client.force_login(user)
    return client


def test_api_setup_name_required():
    """A request without a name gets the name_required code."""
    user = factories.UserFactory()

    response = _client_for(user).post(SETUP_URL, {"name": " "}, format="json")

    assert response.status_code == 400
    assert response.json() == {"code": "name_required", "error": "name is required"}


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
@mock.patch("core.services.setup_service.MessagesService")
def test_api_setup_mailbox_viewer_role_returns_code(mock_messages):
    """A mailbox viewer gets the mailbox role error code."""
    user = factories.UserFactory()
    mock_messages.return_value.get_user_mailboxes.return_value = [
        {"email": "team@example.com", "role": "viewer"}
    ]

    response = _client_for(user).post(
        SETUP_URL,
        {"name": "Team", "mailbox_email": "team@example.com"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "mailbox_role_required",
        "error": "Calendar setup failed.",
    }


@override_settings(FEATURE_MESSAGES_INTEGRATION=False)
def test_api_setup_messages_disabled_returns_code():
    """A mailbox calendar without the Messages integration gets its code."""
    user = factories.UserFactory()

    response = _client_for(user).post(
        SETUP_URL,
        {"name": "Team", "mailbox_email": "team@example.com"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "messages_disabled",
        "error": "Calendar setup failed.",
    }


@override_settings(
    FEATURE_MESSAGES_INTEGRATION=True, OIDC_USERINFO_ORGANIZATION_CLAIM="siret"
)
@mock.patch("core.services.setup_service.MessagesService")
def test_api_setup_mailbox_without_org_returns_code(mock_messages):
    """A mailbox without the organization claim gets its code."""
    user = factories.UserFactory()
    mock_messages.return_value.get_user_mailboxes.return_value = [
        {"email": "team@example.com", "role": "admin"}
    ]

    response = _client_for(user).post(
        SETUP_URL,
        {"name": "Team", "mailbox_email": "team@example.com"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "mailbox_org_unresolved",
        "error": "Calendar setup failed.",
    }


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
@mock.patch("core.services.setup_service.MessagesService")
def test_api_setup_unknown_mailbox_does_not_echo_details(mock_messages):
    """An unknown mailbox gets a code, without the user or mailbox email."""
    user = factories.UserFactory()
    mock_messages.return_value.get_user_mailboxes.return_value = []

    response = _client_for(user).post(
        SETUP_URL,
        {"name": "Team", "mailbox_email": "team@example.com"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "mailbox_access_denied",
        "error": "Calendar setup failed.",
    }


@mock.patch("core.services.setup_service.CalDAVHTTPClient")
def test_api_setup_caldav_failure_hides_internal_details(mock_http):
    """A CalDAV failure does not show the internal host to the client."""
    user = factories.UserFactory()
    mock_http.return_value.internal_request.side_effect = requests.ConnectionError(
        "HTTPConnectionPool(host='caldav', port=80): Max retries exceeded "
        "with url: /internal-api/calendars/"
    )

    response = _client_for(user).post(SETUP_URL, {"name": "Mine"}, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "code": "calendar_creation_failed",
        "error": "Calendar setup failed.",
    }


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
@mock.patch("core.api.viewsets_setup.sync_mailbox_task")
@mock.patch("core.api.viewsets_setup.SetupService")
def test_api_setup_mailbox_enqueues_the_fan_out(mock_service, mock_task):
    """The worker shares a new mailbox calendar with the other users."""
    user = factories.UserFactory()
    mock_service.return_value.setup.return_value = {"calendar_path": "path"}

    response = _client_for(user).post(
        SETUP_URL,
        {"name": "Team", "mailbox_email": "team@example.com"},
        format="json",
    )

    assert response.status_code == 201
    mock_task.delay.assert_called_once_with("team@example.com")


@mock.patch("core.api.viewsets_setup.sync_mailbox_task")
@mock.patch("core.api.viewsets_setup.SetupService")
def test_api_setup_standalone_enqueues_no_fan_out(mock_service, mock_task):
    """A standalone calendar has no mailbox users to sync."""
    user = factories.UserFactory()
    mock_service.return_value.setup.return_value = {"calendar_path": "path"}

    response = _client_for(user).post(SETUP_URL, {"name": "Mine"}, format="json")

    assert response.status_code == 201
    mock_task.delay.assert_not_called()


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
@mock.patch("core.api.viewsets_setup.sync_mailbox_task")
@mock.patch("core.api.viewsets_setup.SetupService")
def test_api_setup_mailbox_ignores_a_failed_enqueue(mock_service, mock_task):
    """The setup succeeds when the fan-out cannot be enqueued."""
    user = factories.UserFactory()
    mock_service.return_value.setup.return_value = {"calendar_path": "path"}
    mock_task.delay.side_effect = ConnectionError("redis down")

    response = _client_for(user).post(
        SETUP_URL,
        {"name": "Team", "mailbox_email": "team@example.com"},
        format="json",
    )

    assert response.status_code == 201
    assert response.json() == {"calendar_path": "path"}
