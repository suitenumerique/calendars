"""Tests for SetupService errors when CalDAV does not apply a mailbox ACL sync."""

import logging
from unittest import mock

from django.test import override_settings

import pytest
import requests

from core import factories
from core.services.setup_service import MailboxSyncError, SetupService
from core.tasks import sync_all_mailbox_acls

pytestmark = pytest.mark.django_db

MAILBOX = {"email": "team@example.com", "role": "admin"}


def _service(internal_request):
    with mock.patch("core.services.setup_service.CalDAVHTTPClient") as mock_http:
        mock_http.return_value.internal_request = internal_request
        service = SetupService()
    service._messages = mock.MagicMock()  # pylint: disable=protected-access
    service.messages.get_user_mailboxes.return_value = [MAILBOX]
    return service


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_sync_user_mailboxes_connection_error_raises():
    """A CalDAV connection error is not reported as an empty sync."""
    service = _service(mock.Mock(side_effect=requests.ConnectionError("refused")))

    with pytest.raises(MailboxSyncError):
        service.sync_user_mailboxes(factories.UserFactory())


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_sync_user_mailboxes_error_status_raises():
    """A CalDAV error status is not reported as an empty sync."""
    service = _service(mock.Mock(return_value=mock.Mock(status_code=500)))

    with pytest.raises(MailboxSyncError):
        service.sync_user_mailboxes(factories.UserFactory())


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_sync_user_mailboxes_without_mailbox_raises():
    """The cleanup of stale shares also reports a CalDAV error."""
    service = _service(mock.Mock(side_effect=requests.ConnectionError("refused")))
    service.messages.get_user_mailboxes.return_value = []

    with pytest.raises(MailboxSyncError):
        service.sync_user_mailboxes(factories.UserFactory())


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_setup_mailbox_ignores_a_failed_fan_out():
    """The setup returns the new calendar when the share fan-out fails."""
    service = _service(mock.Mock(side_effect=requests.ConnectionError("refused")))
    user = factories.UserFactory()

    with (
        mock.patch.object(service, "_get_user_mailbox", return_value=MAILBOX),
        mock.patch(
            "core.services.setup_service._resolve_mailbox_org_id",
            return_value="org-id",
        ),
        mock.patch.object(
            service,
            "_create_calendar",
            return_value={"caller_calendar_uri": "cal-uri"},
        ),
    ):
        result = service.setup(user, "Team", mailbox_email=MAILBOX["email"])

    assert result["calendar_path"] == f"calendars/users/{user.email}/cal-uri"


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_sync_all_mailbox_acls_counts_caldav_errors():
    """The sync task counts a CalDAV error and logs a warning."""
    factories.UserFactory(organization=factories.OrganizationFactory())
    service = _service(mock.Mock(side_effect=requests.ConnectionError("refused")))

    with (
        mock.patch("core.services.setup_service.SetupService", return_value=service),
        mock.patch("core.tasks.logger") as mock_logger,
    ):
        sync_all_mailbox_acls()

    mock_logger.log.assert_called_once_with(
        logging.WARNING, "sync_all_mailbox_acls: synced %d users, %d errors", 0, 1
    )
