"""Tests for the sync_mailbox_acls management command."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError

import pytest

pytestmark = pytest.mark.django_db

COMMAND_MODULE = "core.management.commands.sync_mailbox_acls"


@pytest.fixture(autouse=True)
def messages_enabled(settings):
    """Enable the Messages integration."""
    settings.FEATURE_MESSAGES_INTEGRATION = True


def test_enqueue_sends_the_task():
    """--enqueue sends the sync task and does not sync in place."""
    with (
        mock.patch(f"{COMMAND_MODULE}.sync_all_mailbox_acls") as mock_task,
        mock.patch(f"{COMMAND_MODULE}.SetupService") as mock_service,
    ):
        mock_task.send.return_value = mock.Mock(message_id="msg-1")
        call_command("sync_mailbox_acls", "--enqueue")

    mock_task.send.assert_called_once_with()
    mock_service.assert_not_called()


@pytest.mark.parametrize(
    "target", [["--email", "a@example.com"], ["--mailbox", "team@example.com"]]
)
def test_enqueue_with_a_target_fails(target):
    """--enqueue syncs all users, so it refuses --email and --mailbox."""
    with mock.patch(f"{COMMAND_MODULE}.sync_all_mailbox_acls") as mock_task:
        with pytest.raises(CommandError):
            call_command("sync_mailbox_acls", "--enqueue", *target)

    mock_task.send.assert_not_called()


def test_enqueue_with_feature_disabled(settings):
    """--enqueue sends nothing when the Messages integration is off."""
    settings.FEATURE_MESSAGES_INTEGRATION = False

    with mock.patch(f"{COMMAND_MODULE}.sync_all_mailbox_acls") as mock_task:
        call_command("sync_mailbox_acls", "--enqueue")

    mock_task.send.assert_not_called()


def test_mailbox_prints_the_failed_users():
    """--mailbox prints the count of users that failed."""
    out = StringIO()

    with mock.patch(f"{COMMAND_MODULE}.SetupService") as mock_service:
        mock_service.return_value.sync_mailbox.return_value = (1, 2)
        call_command("sync_mailbox_acls", "--mailbox", "team@example.com", stdout=out)

    assert "Synced 1 user(s) for mailbox team@example.com, 2 error(s)." in (
        out.getvalue()
    )
