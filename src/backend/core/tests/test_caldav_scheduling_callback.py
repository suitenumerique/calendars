"""Tests for the CalDAV scheduling callback view."""

# pylint: disable=missing-function-docstring

from unittest.mock import patch

from django.test import Client

import pytest

from core.tasks import send_invitation_task

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


def test_send_invitation_task_does_not_retry():
    assert send_invitation_task.options["max_retries"] == 0
