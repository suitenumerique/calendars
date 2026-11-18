"""Tests for the errors of a calendar email send.

When the server does not accept the email, the send raises
InvitationNotSentError, and the task retries. Other errors are final.
"""

# pylint: disable=missing-function-docstring

import smtplib
import ssl
from unittest.mock import patch

import pytest
import requests

from core.services.calendar_invitation_service import (
    CalendarInvitationService,
    InvitationNotSentError,
)

ICS_REQUEST = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
METHOD:REQUEST
BEGIN:VEVENT
UID:send-errors-1
DTSTART:20260310T100000Z
DTEND:20260310T110000Z
SUMMARY:Team meeting
ORGANIZER:mailto:alice@example.com
ATTENDEE;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""


def _send(**kwargs):
    return CalendarInvitationService().send_invitation(
        sender_email="mailto:alice@example.com",
        recipient_email="mailto:bob@example.com",
        method="REQUEST",
        icalendar_data=ICS_REQUEST,
        **kwargs,
    )


@pytest.mark.django_db
def test_send_can_be_retried_when_smtp_is_down(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    settings.EMAIL_HOST = "localhost"
    settings.EMAIL_PORT = 1
    with pytest.raises(InvitationNotSentError):
        _send()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPAuthenticationError(535, b"Bad credentials"),
        ssl.SSLCertVerificationError("certificate verify failed"),
    ],
)
def test_send_fails_for_good_on_smtp_configuration_errors(error):
    with patch("django.core.mail.backends.locmem.EmailBackend.open", side_effect=error):
        assert _send() is False


@pytest.mark.django_db
def test_send_can_be_retried_when_smtp_login_fails_for_now():
    with (
        patch(
            "django.core.mail.backends.locmem.EmailBackend.open",
            side_effect=smtplib.SMTPAuthenticationError(
                454, b"Temporary authentication failure"
            ),
        ),
        pytest.raises(InvitationNotSentError),
    ):
        _send()


def _send_with_smtp_error(error):
    with patch(
        "django.core.mail.backends.locmem.EmailBackend.send_messages",
        side_effect=error,
    ):
        return _send()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPSenderRefused(421, b"Try again later", "noreply@example.com"),
        smtplib.SMTPRecipientsRefused({"bob@example.com": (450, b"Greylisted")}),
        smtplib.SMTPDataError(451, b"Try again later"),
    ],
)
def test_send_can_be_retried_when_smtp_refuses_for_now(error):
    with pytest.raises(InvitationNotSentError):
        _send_with_smtp_error(error)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPSenderRefused(550, b"Not allowed", "noreply@example.com"),
        smtplib.SMTPRecipientsRefused({"bob@example.com": (550, b"No such user")}),
        smtplib.SMTPDataError(554, b"Rejected"),
        smtplib.SMTPServerDisconnected("Connection lost after the data"),
    ],
)
def test_send_fails_for_good_on_other_smtp_errors(error):
    assert _send_with_smtp_error(error) is False


@pytest.fixture(name="messages_settings")
def fixture_messages_settings(settings):
    settings.FEATURE_MESSAGES_INTEGRATION = True
    settings.MESSAGES_API_URL = "http://messages.test"
    settings.MESSAGES_API_KEY = "key"
    settings.MESSAGES_CHANNEL_ID = "channel"


def _send_via_messages(target, **lookup):
    with (
        patch(f"core.services.messages_service.MessagesService.{target}", **lookup),
        patch(
            "core.services.messages_service.MessagesService.submit_raw_message"
        ) as mock_submit,
    ):
        try:
            return _send(is_mailbox=True)
        finally:
            mock_submit.assert_not_called()


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


@pytest.mark.django_db
@pytest.mark.usefixtures("messages_settings")
@pytest.mark.parametrize(
    "error",
    [
        requests.ConnectionError(),
        requests.Timeout(),
        _http_error(503),
        _http_error(403),
        requests.exceptions.SSLError("certificate verify failed"),
    ],
)
def test_send_can_be_retried_when_the_mailbox_lookup_fails(error):
    with pytest.raises(InvitationNotSentError):
        _send_via_messages("_request", side_effect=error)


@pytest.mark.django_db
@pytest.mark.usefixtures("messages_settings")
def test_send_fails_for_good_when_the_mailbox_is_not_found():
    assert _send_via_messages("get_mailbox_by_email", return_value=None) is False
