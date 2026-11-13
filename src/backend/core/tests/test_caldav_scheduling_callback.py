"""Tests for the CalDAV scheduling callback view."""

# pylint: disable=missing-function-docstring

from unittest.mock import patch

from django.test import Client

import pytest
from django_dramatiq.models import Task

from core.services.calendar_invitation_service import (
    CalendarInvitationService,
    InvitationNotSentError,
)
from core.task_utils import AdminMiddleware
from core.tasks import (
    INVITATION_SEND_RETRIES,
    InvitationSendError,
    _retry_when_not_sent,
    send_invitation_task,
)

CALLBACK_PATH = "/api/v1.0/caldav-scheduling-callback/"
API_KEY = "callback-test-key"

ICS_REQUEST = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
METHOD:REQUEST
BEGIN:VEVENT
UID:callback-queue-1
DTSTART:20260310T100000Z
DTEND:20260310T110000Z
SUMMARY:Team meeting
ORGANIZER:mailto:alice@example.com
ATTENDEE;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""


@pytest.fixture(autouse=True)
def _api_key(settings):
    settings.CALDAV_INBOUND_API_KEY = API_KEY


def _post_callback():
    return Client().post(
        CALLBACK_PATH,
        data=ICS_REQUEST.encode("utf-8"),
        content_type="text/calendar",
        HTTP_X_LS_API_KEY=API_KEY,
        HTTP_X_LS_SENDER="mailto:alice@example.com",
        HTTP_X_LS_RECIPIENT="mailto:bob@example.com",
        HTTP_X_LS_METHOD="REQUEST",
        HTTP_X_LS_IS_MAILBOX="true",
        HTTP_X_LS_NEW_ATTENDEE="true",
        HTTP_X_LS_ORG_ID="org-1",
    )


def test_callback_queues_the_email():
    with patch("core.api.viewsets_caldav.send_invitation_task.delay") as mock_delay:
        response = _post_callback()

    assert response.status_code == 202
    mock_delay.assert_called_once_with(
        sender_email="alice@example.com",
        recipient_email="bob@example.com",
        method="REQUEST",
        icalendar_data=ICS_REQUEST,
        is_mailbox=True,
        org_id="org-1",
        is_new_attendee=True,
    )


def test_callback_does_not_send_the_email_itself():
    with (
        patch("core.api.viewsets_caldav.send_invitation_task.delay"),
        patch(
            "core.services.calendar_invitation_service"
            ".CalendarInvitationService.send_invitation"
        ) as mock_send,
    ):
        _post_callback()

    mock_send.assert_not_called()


def test_callback_fails_when_the_queue_fails():
    with patch(
        "core.api.viewsets_caldav.send_invitation_task.delay",
        side_effect=ConnectionError("redis is down"),
    ):
        response = _post_callback()

    assert response.status_code == 500


def test_send_invitation_task_retries_only_when_nothing_was_sent():
    not_sent = InvitationNotSentError("smtp is down")
    assert _retry_when_not_sent(0, not_sent)
    assert _retry_when_not_sent(INVITATION_SEND_RETRIES - 1, not_sent)
    assert not _retry_when_not_sent(INVITATION_SEND_RETRIES, not_sent)
    assert not _retry_when_not_sent(0, InvitationSendError("partial failure"))


def test_send_invitation_task_fails_when_the_send_fails():
    with (
        patch(
            "core.services.calendar_invitation_service"
            ".CalendarInvitationService.send_invitation",
            return_value=False,
        ),
        pytest.raises(InvitationSendError),
    ):
        send_invitation_task.fn(
            sender_email="alice@example.com",
            recipient_email="bob@example.com",
            method="REQUEST",
            icalendar_data=ICS_REQUEST,
        )


@pytest.mark.django_db
def test_send_fails_before_sending_when_smtp_is_down(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST = "localhost"
    settings.EMAIL_PORT = 1
    with pytest.raises(InvitationNotSentError):
        CalendarInvitationService().send_invitation(
            sender_email="mailto:alice@example.com",
            recipient_email="mailto:bob@example.com",
            method="REQUEST",
            icalendar_data=ICS_REQUEST,
        )


@pytest.mark.django_db
def test_send_fails_before_sending_when_the_mailbox_is_not_found(settings):
    settings.FEATURE_MESSAGES_INTEGRATION = True
    settings.MESSAGES_API_URL = "http://messages.test"
    settings.MESSAGES_API_KEY = "key"
    settings.MESSAGES_CHANNEL_ID = "channel"
    with (
        patch(
            "core.services.messages_service.MessagesService.get_mailbox_by_email",
            return_value=None,
        ),
        patch(
            "core.services.messages_service.MessagesService.submit_raw_message"
        ) as mock_submit,
        pytest.raises(InvitationNotSentError),
    ):
        CalendarInvitationService().send_invitation(
            sender_email="mailto:alice@example.com",
            recipient_email="mailto:bob@example.com",
            method="REQUEST",
            icalendar_data=ICS_REQUEST,
            is_mailbox=True,
        )
    mock_submit.assert_not_called()


def _record_task():
    message = send_invitation_task.message(
        sender_email="alice@example.com",
        recipient_email="bob@example.com",
        method="REQUEST",
        icalendar_data=ICS_REQUEST,
    )
    Task.tasks.create_or_update_from_message(
        message,
        status=Task.STATUS_RUNNING,
        actor_name=message.actor_name,
        queue_name=message.queue_name,
    )
    return message


@pytest.mark.django_db
def test_admin_middleware_deletes_a_done_email_task():
    message = _record_task()

    AdminMiddleware().after_process_message(None, message)

    assert not Task.tasks.filter(id=message.message_id).exists()


@pytest.mark.django_db
def test_admin_middleware_keeps_a_failed_email_task():
    message = _record_task()

    AdminMiddleware().after_process_message(
        None, message, exception=InvitationSendError("failed")
    )

    assert Task.tasks.get(id=message.message_id).status == Task.STATUS_FAILED
