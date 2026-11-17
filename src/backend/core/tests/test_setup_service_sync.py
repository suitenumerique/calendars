"""Tests for the mailbox ACL sync of SetupService against CalDAV."""

import logging
import threading
import time
from unittest import mock

from django.db import connection
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


def _sync_in_thread(service, user, errors):
    try:
        service.sync_user_mailboxes(user)
    except Exception as exc:  # pylint: disable=broad-exception-caught  # noqa: BLE001
        errors.append(exc)
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
@override_settings(FEATURE_MESSAGES_INTEGRATION=True)
def test_sync_user_mailboxes_waits_for_a_running_sync():
    """An older Messages answer does not reach CalDAV after a newer one.

    The first sync reads "member of the mailbox" and waits. The second
    sync reads "removed from the mailbox". The removal must reach CalDAV
    last, or the first sync restores the share.
    """
    user = factories.UserFactory()
    first_lookup_started = threading.Event()
    release_first_lookup = threading.Event()
    applied = []
    errors = []

    def get_user_mailboxes(*args, **kwargs):
        if not first_lookup_started.is_set():
            first_lookup_started.set()
            release_first_lookup.wait(timeout=5)
            return [MAILBOX]
        return []

    def internal_request(*args, json, **kwargs):  # pylint: disable=redefined-outer-name
        applied.append(json["shares"])
        return mock.Mock(status_code=200, json=mock.Mock(return_value={"active": []}))

    service = _service(mock.Mock(side_effect=internal_request))
    service.messages.get_user_mailboxes.side_effect = get_user_mailboxes

    first = threading.Thread(target=_sync_in_thread, args=(service, user, errors))
    first.start()
    assert first_lookup_started.wait(timeout=5)
    second = threading.Thread(target=_sync_in_thread, args=(service, user, errors))
    second.start()

    # Give the second sync the time to reach CalDAV if nothing stops it.
    time.sleep(0.5)
    assert not applied

    release_first_lookup.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not errors
    assert len(applied) == 2
    assert applied[-1] == []
