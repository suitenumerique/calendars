"""Tests for the mailbox ACL sync of SetupService against CalDAV."""

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
def test_sync_all_mailbox_acls_counts_caldav_errors(core_caplog):
    """The sync task counts a CalDAV error and logs a warning."""
    factories.UserFactory(organization=factories.OrganizationFactory())
    service = _service(mock.Mock(side_effect=requests.ConnectionError("refused")))

    with mock.patch("core.services.setup_service.SetupService", return_value=service):
        sync_all_mailbox_acls()

    assert (
        "core.tasks",
        logging.WARNING,
        "sync_all_mailbox_acls: synced 0 users, 1 errors",
    ) in core_caplog.record_tuples


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_sync_mailbox_does_not_restore_a_revoked_share():
    """A mailbox sync with an old user list does not restore a share.

    The mailbox sync reads "Alice is a member". Then Alice is removed
    from the mailbox, and her user sync removes her share. The mailbox
    sync must not then send the share of its old list to CalDAV.
    """
    alice = factories.UserFactory()
    applied = []

    def internal_request(*args, json, **kwargs):  # pylint: disable=redefined-outer-name
        applied.append(json)
        return mock.Mock(status_code=200, json=mock.Mock(return_value={"active": []}))

    service = _service(mock.Mock(side_effect=internal_request))
    service.messages.get_user_mailboxes.return_value = []

    def get_mailbox_by_email(mailbox_email, **_kwargs):
        snapshot = {"email": mailbox_email, "users": [{"email": alice.email}]}
        service.sync_user_mailboxes(alice)
        return snapshot

    service.messages.get_mailbox_by_email.side_effect = get_mailbox_by_email

    result = service.sync_mailbox(MAILBOX["email"])

    assert applied[-1] == {"shares": [], "full_sync_users": [alice.email]}
    assert result == (1, 0)


@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_sync_mailbox_counts_the_failed_users():
    """A failed user sync does not stop the next one, and the result counts it."""
    users = factories.UserFactory.create_batch(2)
    confirmed = mock.Mock(status_code=200, json=mock.Mock(return_value={"active": []}))
    service = _service(
        mock.Mock(side_effect=[requests.ConnectionError("refused"), confirmed])
    )
    service.messages.get_mailbox_by_email.return_value = {
        "email": MAILBOX["email"],
        "users": [{"email": user.email} for user in users],
    }

    assert service.sync_mailbox(MAILBOX["email"]) == (1, 1)
