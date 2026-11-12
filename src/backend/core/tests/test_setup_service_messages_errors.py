"""Tests for the mailbox ACL sync when the Messages lookup fails.

A failed lookup must not look like "no mailboxes". Otherwise the sync
removes all the sync-managed shares of the user.
"""

from unittest import mock

from django.core.cache import cache

import pytest
import requests

from core import factories
from core.services.messages_service import MessagesService, MessagesServiceError
from core.services.setup_service import SetupService
from core.tasks import sync_all_mailbox_acls

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def messages_settings(settings):
    """Enable Messages and do not reuse answers from another test."""
    settings.FEATURE_MESSAGES_INTEGRATION = True
    settings.MESSAGES_API_URL = "https://messages.test"
    settings.MESSAGES_API_KEY = "key"
    settings.MESSAGES_CHANNEL_ID = "channel"
    cache.clear()


def _service():
    """Return a SetupService and the mock of its CalDAV internal requests."""
    internal_request = mock.Mock(
        return_value=mock.Mock(
            status_code=200, json=mock.Mock(return_value={"active": []})
        )
    )
    with mock.patch("core.services.setup_service.CalDAVHTTPClient") as mock_http:
        mock_http.return_value.internal_request = internal_request
        service = SetupService()
    return service, internal_request


def _messages_answer(results):
    return mock.Mock(json=mock.Mock(return_value={"results": results}))


def test_messages_failure_keeps_the_shares():
    """A Messages error raises and sends no sync to CalDAV."""
    service, internal_request = _service()

    with mock.patch.object(
        MessagesService, "_request", side_effect=requests.HTTPError("503")
    ):
        with pytest.raises(MessagesServiceError):
            service.sync_user_mailboxes(factories.UserFactory())

    internal_request.assert_not_called()


def test_messages_empty_answer_removes_the_shares():
    """An empty Messages answer removes the stale shares of the user."""
    service, internal_request = _service()
    user = factories.UserFactory()

    with mock.patch.object(
        MessagesService, "_request", return_value=_messages_answer([])
    ):
        result = service.sync_user_mailboxes(user)

    assert result == {"available_mailboxes": [], "active_mailbox_calendars": []}
    internal_request.assert_called_once_with(
        "POST",
        user,
        "internal-api/sync-mailbox-acls/",
        json={"shares": [], "full_sync_users": [user.email]},
    )


def test_sync_task_counts_a_messages_failure():
    """The sync task counts a Messages error and sends no sync to CalDAV."""
    factories.UserFactory(organization=factories.OrganizationFactory())
    service, internal_request = _service()

    with (
        mock.patch("core.services.setup_service.SetupService", return_value=service),
        mock.patch.object(
            MessagesService, "_request", side_effect=requests.ConnectionError("down")
        ),
        mock.patch("core.tasks.logger") as mock_logger,
    ):
        sync_all_mailbox_acls()

    assert mock_logger.log.call_args.args[2:] == (0, 1)
    internal_request.assert_not_called()


def test_mailbox_lookup_by_email_failure_returns_none():
    """A failed lookup by mailbox email keeps returning None."""
    with mock.patch.object(
        MessagesService, "_request", side_effect=requests.HTTPError("503")
    ):
        assert MessagesService().get_mailbox_by_email("team@example.com") is None


@pytest.mark.parametrize("email", [None, ""])
def test_user_without_email_is_skipped(email):
    """A user without an email does not call Messages or CalDAV."""
    service, internal_request = _service()
    user = factories.UserFactory(email=email)

    with mock.patch.object(MessagesService, "_request") as messages_request:
        result = service.sync_user_mailboxes(user)

    assert result == {"available_mailboxes": [], "active_mailbox_calendars": []}
    messages_request.assert_not_called()
    internal_request.assert_not_called()
