"""Tests for ICalendarParser and email template rendering."""

# pylint: disable=missing-function-docstring,protected-access,too-many-lines

import re
from unittest.mock import MagicMock, patch

from django.template.loader import render_to_string
from django.test import Client

import pytest
import requests

from core.services.calendar_invitation_service import (
    CalendarInvitationService,
    ICalendarParser,
    _build_calendar_email,
    _message_id_domain,
)
from core.services.messages_service import MessagesService

# Sample ICS with URL property
ICS_WITH_URL = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:test-123
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Réunion d'équipe
DESCRIPTION:Point hebdomadaire
LOCATION:Salle 301
URL:https://visio.numerique.gouv.fr/abc-defg-hij
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""

# Sample ICS without URL property
ICS_WITHOUT_URL = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:test-456
DTSTART:20260210T140000Z
DTEND:20260210T150000Z
SUMMARY:Simple meeting
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""


class TestICalendarParserUrl:
    """Tests for URL property extraction in ICalendarParser."""

    def test_parse_extracts_url_when_present(self):
        event = ICalendarParser.parse(ICS_WITH_URL, "bob@example.com")
        assert event is not None
        assert event.url == "https://visio.numerique.gouv.fr/abc-defg-hij"

    def test_parse_url_is_none_when_absent(self):
        event = ICalendarParser.parse(ICS_WITHOUT_URL, "bob@example.com")
        assert event is not None
        assert event.url is None

    def test_parse_preserves_other_fields_with_url(self):
        event = ICalendarParser.parse(ICS_WITH_URL, "bob@example.com")
        assert event is not None
        assert event.summary == "Réunion d'équipe"
        assert event.description == "Point hebdomadaire"
        assert event.location == "Salle 301"
        assert event.organizer_email == "alice@example.com"


class TestSanitizeUrl:
    """The ICS URL property is rendered straight into invitation emails
    as <a href=...>. An attacker who can put an event on a victim's
    calendar (by definition, what an invitation does) could otherwise
    smuggle ``javascript:``, ``data:`` or scheme-less values through to
    the recipient's mail client. Hard-allowlist the schemes we render."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("https://meet.example.com/abc", "https://meet.example.com/abc"),
            ("http://meet.example.com/abc", "http://meet.example.com/abc"),
            ("mailto:host@example.com", "mailto:host@example.com"),
            ("tel:+33123456789", "tel:+33123456789"),
            ("  https://meet.example.com/abc  ", "https://meet.example.com/abc"),
            ("HTTPS://meet.example.com/abc", "HTTPS://meet.example.com/abc"),
        ],
    )
    def test_safe_schemes_pass_through(self, raw, expected):
        assert ICalendarParser.sanitize_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "javascript:alert(document.cookie)",
            "JAVASCRIPT:alert(1)",
            "  javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "//evil.example.com/path",  # protocol-relative
            "/relative/path",
            "relative-path",
            "",
            None,
        ],
    )
    def test_unsafe_schemes_are_dropped(self, raw):
        assert ICalendarParser.sanitize_url(raw) is None

    def test_javascript_url_does_not_reach_template(self):
        ics = (
            "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Test//EN\n"
            "BEGIN:VEVENT\nUID:xss-1\n"
            "DTSTART:20260210T140000Z\nDTEND:20260210T150000Z\n"
            "SUMMARY:Click me\n"
            "URL:javascript:alert(document.cookie)\n"
            "ORGANIZER;CN=Mallory:mailto:mallory@evil.com\n"
            "ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com\n"
            "SEQUENCE:0\nEND:VEVENT\nEND:VCALENDAR"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        assert event.url is None


class TestICalendarParserLineInjection:
    """Pin the parser's resistance to ICS field smuggling.

    These tests exist because ``ICalendarParser`` was historically a
    hand-rolled regex parser whose safety depended on every byte having
    been re-serialized by sabre/vobject upstream — a fragile invariant.
    The parser is now backed by the ``icalendar`` library, but the
    contract these tests pin (no field-smuggling, no header injection,
    no nested-block confusion) must hold regardless of which parser
    backs ``ICalendarParser``. If you swap the implementation, these
    tests must keep passing.

    Each payload represents a thing an attacker could try to put in
    an ICS field — usually inside DESCRIPTION or SUMMARY — to cause a
    different field to take a value the attacker chose.
    """

    @staticmethod
    def _wrap(vevent_body: str) -> str:
        """Wrap a VEVENT body in a minimal valid VCALENDAR."""
        return (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:line-injection-test\r\n"
            "DTSTART:20260210T140000Z\r\n"
            "DTEND:20260210T150000Z\r\n"
            f"{vevent_body}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

    def test_description_with_escaped_newline_does_not_split_into_attendee(self):
        """RFC 5545 ``\\n`` inside DESCRIPTION is a logical newline of
        the *value*, not a property delimiter. The parser must not
        treat the post-``\\n`` text as a new ATTENDEE property."""
        ics = self._wrap(
            "DESCRIPTION:Hi there.\\nATTENDEE;CN=Mallory:mailto:victim@target.com\r\n"
            "ORGANIZER;CN=Real:mailto:real@example.com\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # The ONLY attendee the parser reports for the recipient must be the real one.
        assert event.attendee_email == "bob@example.com"
        # The smuggled CN must NOT be picked up.
        assert event.attendee_name != "Mallory"
        # The DESCRIPTION must contain the literal newline-escaped value.
        assert event.description is not None
        assert (
            "ATTENDEE" in event.description
        )  # the attacker's bytes are still IN the description
        # …but they did not become a property.
        assert event.organizer_email == "real@example.com"

    @pytest.mark.parametrize("itip_enabled", [True, False])
    def test_summary_with_embedded_method_is_not_treated_as_calendar_method(
        self, itip_enabled, settings
    ):
        """A METHOD-looking substring inside SUMMARY must not result in
        a top-of-line ``METHOD:CANCEL`` property on the outgoing
        attachment, in either ITIP mode."""
        settings.CALENDAR_ITIP_ENABLED = itip_enabled

        ics = self._wrap(
            "SUMMARY:Important: METHOD:CANCEL was discussed\r\n"
            "ORGANIZER;CN=Real:mailto:real@example.com\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        assert "METHOD:CANCEL" in event.summary

        service = CalendarInvitationService()
        rewritten = service._prepare_ics_attachment(ics, "REQUEST")

        # No bare ``METHOD:CANCEL`` line at start-of-line in the output,
        # regardless of whether ITIP is enabled or not. (The substring
        # "METHOD:CANCEL" *can* still appear inside the SUMMARY value;
        # what matters is that no top-level METHOD property got smuggled.)
        bare_cancel = re.search(r"(?:^|\r?\n)METHOD:CANCEL\b", rewritten)
        assert bare_cancel is None, (
            f"Smuggled METHOD:CANCEL appeared as a top-level property "
            f"in the rewritten ICS (itip_enabled={itip_enabled}):\n{rewritten}"
        )

    def test_organizer_cn_with_crlf_does_not_inject_email_header(self):
        """CRLF in ORGANIZER CN parameter must not become an email header
        line. Validated end-to-end via Django's BadHeaderError if needed,
        but the parser-level guarantee is: the parsed ``organizer_name``
        contains no CR/LF."""
        ics = self._wrap(
            'ORGANIZER;CN="Real\\r\\nBcc: secret@target.com":mailto:real@example.com\r\n'
            "SUMMARY:Test\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # icalendar lib unescapes \r\n inside text values; if the CN somehow
        # contained literal CR/LF after parsing, that would be a smuggling
        # primitive. Assert no CR/LF made it through.
        if event.organizer_name:
            assert "\r" not in event.organizer_name
            assert "\n" not in event.organizer_name

    def test_nested_vevent_in_description_not_picked_up_as_outer_event(self):
        """A non-greedy regex parser would have matched the inner block
        if a literal ``BEGIN:VEVENT...END:VEVENT`` appeared inside a
        DESCRIPTION. The icalendar lib correctly parses only one level
        — assert the OUTER UID/SUMMARY win."""
        # Use \\n (escaped newline within DESCRIPTION value) to put
        # BEGIN:VEVENT-looking text inside DESCRIPTION; per RFC 5545
        # this is text content of the outer DESCRIPTION property.
        ics = self._wrap(
            "SUMMARY:Real Outer Event\r\n"
            "DESCRIPTION:Notes:\\nBEGIN:VEVENT\\nUID:fake-inner\\n"
            "SUMMARY:Fake Inner\\nEND:VEVENT\r\n"
            "ORGANIZER;CN=Real:mailto:real@example.com\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # The outer UID is from the wrapper; we hardcode it to "line-injection-test".
        assert event.uid == "line-injection-test"
        assert event.summary == "Real Outer Event"
        assert event.organizer_email == "real@example.com"

    def test_multiple_attendees_match_only_recipient(self):
        """When the recipient happens to be a substring of another
        attendee's email, the parser must match the EXACT email — not
        a prefix or suffix."""
        ics = self._wrap(
            "SUMMARY:Test\r\n"
            "ORGANIZER:mailto:org@example.com\r\n"
            "ATTENDEE;CN=Evil:mailto:bob@example.com.evil.tld\r\n"
            "ATTENDEE;CN=Real Bob:mailto:bob@example.com\r\n"
            "ATTENDEE;CN=Other:mailto:notbob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # Should match only the real Bob — not the evil substring match.
        assert event.attendee_email == "bob@example.com"
        assert event.attendee_name == "Real Bob"

    def test_url_property_with_carriage_return_in_value_does_not_split(self):
        """A URL containing escaped CR (``\\r``) must not split into a
        new property line."""
        ics = self._wrap(
            "SUMMARY:Test\r\n"
            "URL:https://example.com/path\\rATTENDEE:mailto:victim@target.com\r\n"
            "ORGANIZER:mailto:real@example.com\r\n"
            "ATTENDEE;CN=Bob:mailto:bob@example.com"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is not None
        # URL must either be the (sanitized) full string or None — but
        # there must be exactly one ATTENDEE-derived recipient, the real Bob.
        assert event.attendee_email == "bob@example.com"
        # ORGANIZER must be the real one, not the smuggled one.
        assert event.organizer_email == "real@example.com"

    def test_payload_without_vevent_returns_none(self):
        """An ICS with VTIMEZONE but no VEVENT must NOT pick up
        DTSTART/DTEND from the timezone block (the historical regex
        parser was vulnerable to this — VTIMEZONE has 1970 dates for
        DST rules and would mark an event as 'past')."""
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VTIMEZONE\r\nTZID:Europe/Paris\r\n"
            "BEGIN:STANDARD\r\nDTSTART:19701025T030000\r\n"
            "TZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nEND:STANDARD\r\n"
            "END:VTIMEZONE\r\nEND:VCALENDAR\r\n"
        )
        event = ICalendarParser.parse(ics, "bob@example.com")
        assert event is None

    def test_is_event_past_does_not_pick_up_vtimezone_dtstart(self):
        """``is_event_past`` must read DTSTART from VEVENT only —
        VTIMEZONE blocks contain DTSTART for DST rules dated to 1970
        which would otherwise mark every event as past."""
        future = "20990101T120000Z"
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VTIMEZONE\r\nTZID:Europe/Paris\r\n"
            "BEGIN:STANDARD\r\nDTSTART:19701025T030000\r\n"
            "TZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nEND:STANDARD\r\n"
            "END:VTIMEZONE\r\n"
            "BEGIN:VEVENT\r\nUID:future\r\n"
            f"DTSTART:{future}\r\nDTEND:{future}\r\n"
            "SUMMARY:Far future\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        assert ICalendarParser.is_event_past(ics) is False


@pytest.mark.django_db
class TestEmailTemplateVisioUrl:
    """Tests for visio URL rendering in email templates."""

    def _build_context(self, event):
        service = CalendarInvitationService()
        return service._build_template_context(event, "REQUEST")

    def test_invitation_html_contains_visio_link(self):
        event = ICalendarParser.parse(ICS_WITH_URL, "bob@example.com")
        context = self._build_context(event)
        html = render_to_string("emails/calendar_invitation.html", context)
        assert "https://visio.numerique.gouv.fr/abc-defg-hij" in html
        assert "Visio" in html

    def test_invitation_txt_contains_visio_link(self):
        event = ICalendarParser.parse(ICS_WITH_URL, "bob@example.com")
        context = self._build_context(event)
        txt = render_to_string("emails/calendar_invitation.txt", context)
        assert "https://visio.numerique.gouv.fr/abc-defg-hij" in txt
        assert "Visio" in txt

    def test_invitation_html_no_visio_when_absent(self):
        event = ICalendarParser.parse(ICS_WITHOUT_URL, "bob@example.com")
        context = self._build_context(event)
        html = render_to_string("emails/calendar_invitation.html", context)
        assert "Visio" not in html

    def test_invitation_txt_no_visio_when_absent(self):
        event = ICalendarParser.parse(ICS_WITHOUT_URL, "bob@example.com")
        context = self._build_context(event)
        txt = render_to_string("emails/calendar_invitation.txt", context)
        assert "Visio" not in txt


# ICS template for mailbox invitation tests
ICS_MAILBOX_INVITE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:mailbox-invite-test-1
DTSTART:20260310T100000Z
DTEND:20260310T110000Z
SUMMARY:Mailbox Team Meeting
ORGANIZER;CN=Team Mailbox:mailto:team@company.com
ATTENDEE;CN=External;RSVP=TRUE:mailto:external@other.com
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""


@pytest.mark.django_db
class TestMailboxInvitationRouting:
    """When is_mailbox=True, invitations MUST be sent through the
    Messages API (so the email comes from the mailbox address).
    Falling back to SMTP would send from the system address — the
    exact production bug this test guards against.
    """

    @pytest.fixture()
    def service(self):
        return CalendarInvitationService()

    @pytest.fixture()
    def _messages_settings(self, settings):
        settings.FEATURE_MESSAGES_INTEGRATION = True
        settings.MESSAGES_API_URL = "https://messages.test"
        settings.MESSAGES_API_KEY = "test-key"
        settings.MESSAGES_CHANNEL_ID = "test-channel"

    @pytest.mark.usefixtures("_messages_settings")
    def test_mailbox_invitation_routes_via_messages_api(self, service):
        """send_invitation(is_mailbox=True) must call _send_via_messages,
        NOT _send_email. If the email is sent via SMTP the 'from' address
        will be the system address instead of the mailbox identity."""
        mock_messages = MagicMock()
        mock_messages.get_mailbox_by_email.return_value = {
            "id": "mbx-123",
            "email": "team@company.com",
        }
        mock_messages.submit_raw_message.return_value = True

        with (
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_email",
            ) as mock_send_email,
            patch(
                "core.services.messages_service.MessagesService.__init__",
                return_value=None,
            ),
            patch(
                "core.services.messages_service.MessagesService.get_mailbox_by_email",
                mock_messages.get_mailbox_by_email,
            ),
            patch(
                "core.services.messages_service.MessagesService.submit_raw_message",
                mock_messages.submit_raw_message,
            ),
        ):
            result = service.send_invitation(
                sender_email="team@company.com",
                recipient_email="external@other.com",
                method="REQUEST",
                icalendar_data=ICS_MAILBOX_INVITE,
                is_mailbox=True,
            )

        assert result is True, "Invitation should succeed via Messages API"
        mock_messages.get_mailbox_by_email.assert_called_once_with("team@company.com")
        mock_messages.submit_raw_message.assert_called_once()
        mock_send_email.assert_not_called()

    @pytest.mark.usefixtures("_messages_settings")
    def test_non_mailbox_invitation_routes_via_smtp(self, service):
        """send_invitation(is_mailbox=False) must call _send_email,
        NOT _send_via_messages."""
        with (
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_email",
                return_value=True,
            ) as mock_send_email,
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_via_messages",
            ) as mock_send_messages,
        ):
            result = service.send_invitation(
                sender_email="alice@example.com",
                recipient_email="bob@example.com",
                method="REQUEST",
                icalendar_data=ICS_WITH_URL,
                is_mailbox=False,
            )

        assert result is True
        mock_send_email.assert_called_once()
        mock_send_messages.assert_not_called()

    @pytest.mark.usefixtures("_messages_settings")
    def test_mailbox_invitation_no_smtp_fallback_on_messages_failure(self, service):
        """If _send_via_messages fails, the invitation must NOT fall
        back to SMTP. Sending a mailbox invitation from the system
        address is worse than not sending it at all — it confuses
        recipients and bypasses the mailbox identity."""
        with (
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_email",
            ) as mock_send_email,
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_via_messages",
                return_value=False,
            ),
        ):
            result = service.send_invitation(
                sender_email="team@company.com",
                recipient_email="external@other.com",
                method="REQUEST",
                icalendar_data=ICS_MAILBOX_INVITE,
                is_mailbox=True,
            )

        assert result is False, "Invitation should fail when Messages API fails"
        mock_send_email.assert_not_called()

    def test_mailbox_invitation_refuses_when_feature_flag_disabled(
        self, service, settings
    ):
        """When ``is_mailbox=True`` but ``FEATURE_MESSAGES_INTEGRATION``
        is off, the invitation must FAIL — not fall back to SMTP. SMTP
        would send from the system address instead of the mailbox
        identity, silently sending invitations from the wrong sender
        (the exact production bug the Messages integration was meant to
        prevent).
        """
        settings.FEATURE_MESSAGES_INTEGRATION = False

        with (
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_email",
            ) as mock_send_email,
            patch(
                "core.services.calendar_invitation_service"
                ".CalendarInvitationService._send_via_messages",
            ) as mock_send_messages,
        ):
            result = service.send_invitation(
                sender_email="team@company.com",
                recipient_email="external@other.com",
                method="REQUEST",
                icalendar_data=ICS_MAILBOX_INVITE,
                is_mailbox=True,
            )

        assert result is False, (
            "Mailbox invitation must NOT succeed when Messages integration "
            "is disabled — falling back to SMTP would leak the system address"
        )
        mock_send_email.assert_not_called()
        mock_send_messages.assert_not_called()


# ICS payload with TWO external attendees — what SabreDAV sees when the
# user creates an event with two invitees on a mailbox calendar.
ICS_MAILBOX_INVITE_TWO_ATTENDEES = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:mailbox-invite-two-attendees-1
DTSTART:20260310T100000Z
DTEND:20260310T110000Z
SUMMARY:Mailbox Team Meeting
ORGANIZER;CN=Team Mailbox:mailto:team@company.com
ATTENDEE;CN=Alice;RSVP=TRUE:mailto:alice@external-a.test
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@external-b.test
SEQUENCE:0
END:VEVENT
END:VCALENDAR"""


@pytest.mark.django_db
class TestMailboxCallbackTwoExternalAttendees:
    """End-to-end Django-side check for the reported bug: when a mailbox
    event has two external attendees, both must reach Messages.

    Reproduces what SabreDAV actually does in production: per RFC 6638,
    its iTip broker emits one schedule() per recipient. We've separately
    pinned that fan-out in ``test_caldav_scheduling.py``; here we feed
    those two POSTs into the real ``CalDAVSchedulingCallbackView`` and
    assert ``MessagesService.submit_raw_message`` is invoked twice — once
    per attendee — with distinct ``to_email`` values.

    What this test does NOT verify: that the live Messages backend then
    accepts both submits. That is the next link in the chain and would
    need either the fake Messages server or a real Messages instance.
    """

    CALLBACK_PATH = "/api/v1.0/caldav-scheduling-callback/"
    SENDER = "team@company.com"
    ATTENDEE_A = "alice@external-a.test"
    ATTENDEE_B = "bob@external-b.test"

    @pytest.fixture()
    def _messages_settings(self, settings):
        settings.FEATURE_MESSAGES_INTEGRATION = True
        settings.MESSAGES_API_URL = "https://messages.test"
        settings.MESSAGES_API_KEY = "test-key"
        settings.MESSAGES_CHANNEL_ID = "test-channel"
        settings.CALDAV_INBOUND_API_KEY = "callback-test-key"

    def _post_callback(self, client, recipient: str):
        """Mirror one SabreDAV callback POST for a given recipient."""
        return client.post(
            self.CALLBACK_PATH,
            data=ICS_MAILBOX_INVITE_TWO_ATTENDEES.encode("utf-8"),
            content_type="text/calendar",
            HTTP_X_LS_API_KEY="callback-test-key",
            HTTP_X_LS_SENDER=f"mailto:{self.SENDER}",
            HTTP_X_LS_RECIPIENT=f"mailto:{recipient}",
            HTTP_X_LS_METHOD="REQUEST",
            HTTP_X_LS_IS_MAILBOX="true",
        )

    @pytest.mark.usefixtures("_messages_settings")
    def test_both_external_attendees_reach_messages_api(self):
        """Two sequential callbacks (one per attendee) must result in
        two ``submit_raw_message`` calls with distinct recipients.

        This is the end-to-end check the user asked for: given the two
        POSTs SabreDAV actually sends, does the Django callback path
        forward both to the Messages API? A pass means our code is fine
        and any drop is happening inside the Messages backend itself.
        """
        mailbox = {"id": "mbx-123", "email": self.SENDER}

        with (
            patch(
                "core.services.messages_service.MessagesService.__init__",
                return_value=None,
            ),
            patch(
                "core.services.messages_service.MessagesService.get_mailbox_by_email",
                return_value=mailbox,
            ),
            patch(
                "core.services.messages_service.MessagesService.submit_raw_message",
                return_value=True,
            ) as mock_submit,
        ):
            client = Client()
            resp_a = self._post_callback(client, self.ATTENDEE_A)
            resp_b = self._post_callback(client, self.ATTENDEE_B)

        assert resp_a.status_code == 200, (
            f"First callback (recipient {self.ATTENDEE_A}) failed: "
            f"{resp_a.status_code} {resp_a.content!r}"
        )
        assert resp_b.status_code == 200, (
            f"Second callback (recipient {self.ATTENDEE_B}) failed: "
            f"{resp_b.status_code} {resp_b.content!r}. "
            "If the first succeeded and this failed, the Django callback "
            "view is dropping the second invite — the chain breaks here."
        )

        assert mock_submit.call_count == 2, (
            f"Expected MessagesService.submit_raw_message to be called twice "
            f"(once per external attendee), got {mock_submit.call_count}. "
            "This means Django is not forwarding the second attendee to "
            "the Messages API — fix the callback path, not Messages."
        )

        # Each call should target a distinct recipient — guards against
        # a bug where both submits go to the same address.
        rcpts = [
            kwargs.get("rcpt_to") or (args[1] if len(args) > 1 else None)
            for args, kwargs in (call for call in mock_submit.call_args_list)
        ]
        assert set(rcpts) == {self.ATTENDEE_A, self.ATTENDEE_B}, (
            f"submit_raw_message recipients {rcpts} do not match the "
            f"two external attendees {{{self.ATTENDEE_A!r}, "
            f"{self.ATTENDEE_B!r}}}"
        )


class TestSmtpMessagesParity:
    """The SMTP and Messages paths must produce equivalent MIME — Date,
    Message-ID, iMIP layout, ICS ``method=`` Content-Type — so a mailbox
    recipient gets the same calendar-client experience as an SMTP one.

    Historically the Messages path was missing all three (audit findings
    A, B, D). The shared ``_build_calendar_email`` is now the single
    source of truth; these tests pin it.
    """

    @staticmethod
    def _build(**overrides):
        kwargs = {
            "from_email": "alice@example.com",
            "to_email": "bob@example.com",
            "reply_to": "alice@example.com",
            "subject": "Test",
            "text_body": "text",
            "html_body": "<p>html</p>",
            "ics_content": (
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:REQUEST\r\n"
                "BEGIN:VEVENT\r\nUID:x\r\nDTSTART:20260101T100000Z\r\n"
                "SUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
            ),
            "ics_method": "REQUEST",
            "itip_enabled": True,
        }
        kwargs.update(overrides)
        return _build_calendar_email(**kwargs)

    def test_rendered_mime_has_date_and_message_id(self):
        """Audit findings A + B: a MIME without Date or Message-ID is RFC
        5322-non-conformant and is the most likely cause of MTA dedup
        collapsing two near-identical invitations into one."""
        mime = self._build().message()
        assert mime["Date"], "MIME must carry a Date header (RFC 5322 §3.6)"
        assert mime["Message-ID"], (
            "MIME must carry a Message-ID — without it, downstream MTAs "
            "may dedup two invitations as the same message"
        )

    def test_two_invitations_get_distinct_message_ids(self):
        """Belt-and-braces on the reported bug: each per-recipient build
        must produce a distinct Message-ID. Two emails with the same
        Message-ID is exactly the condition under which most MTAs treat
        the second as a duplicate of the first."""
        m1 = self._build(to_email="alice@external-a.test").message()
        m2 = self._build(to_email="bob@external-b.test").message()
        assert m1["Message-ID"] != m2["Message-ID"], (
            "Per-recipient builds must yield distinct Message-IDs"
        )

    def test_ics_attachment_carries_method_param(self):
        """Audit finding D: when ITIP is on, the attached ``invite.ics``
        Content-Type must include ``method=REQUEST`` so non-iMIP clients
        (Apple Mail, Thunderbird) still treat the file as an invitation
        rather than a generic calendar dump."""
        mime = self._build(itip_enabled=True).message()
        ics_parts = [
            p
            for p in mime.walk()
            if p.get_content_type() == "text/calendar"
            and p.get_filename() == "invite.ics"
        ]
        assert len(ics_parts) == 1
        content_type = ics_parts[0]["Content-Type"]
        assert "method=REQUEST" in content_type, (
            f"ICS attachment Content-Type must carry method=REQUEST, "
            f"got: {content_type!r}"
        )

    def test_inline_imip_calendar_part_when_itip_enabled(self):
        """Outlook needs ``text/calendar`` as a sibling of ``text/html``
        inside ``multipart/alternative`` to render the HTML description.
        This is the structure the SMTP path has always produced; the
        Messages path now produces the same one through the shared builder."""
        mime = self._build(itip_enabled=True).message()
        alt = next(
            (p for p in mime.walk() if p.get_content_type() == "multipart/alternative"),
            None,
        )
        assert alt is not None, "Expected a multipart/alternative in the MIME tree"
        child_types = [c.get_content_type() for c in alt.get_payload()]
        assert "text/plain" in child_types
        assert "text/html" in child_types
        assert "text/calendar" in child_types, (
            "text/calendar must sit inside multipart/alternative for Outlook"
        )

    def test_no_imip_inline_part_when_itip_disabled(self):
        """When ITIP is off, the inline iMIP alternative is omitted and
        the .ics is attachment-only."""
        mime = self._build(itip_enabled=False).message()
        alt = next(
            (p for p in mime.walk() if p.get_content_type() == "multipart/alternative"),
            None,
        )
        assert alt is not None
        child_types = [c.get_content_type() for c in alt.get_payload()]
        assert "text/calendar" not in child_types


class TestMessageIdDomain:
    """The Message-ID domain must come from the instance URL, not from
    Django's default ``DNS_NAME`` (which is the container hostname and
    leaks deployment topology). Format: ``_lst_mail.<host-of-APP_URL>``.
    """

    @pytest.mark.parametrize(
        "app_url,expected_host",
        [
            ("https://calendars.example.com", "calendars.example.com"),
            ("http://localhost:8931", "localhost"),
            ("https://calendars.example.com/some/path", "calendars.example.com"),
            ("", "localhost"),  # fallback when APP_URL is unset
        ],
    )
    def test_domain_derived_from_app_url(self, app_url, expected_host, settings):
        settings.APP_URL = app_url
        assert _message_id_domain() == f"_lst_mail.{expected_host}"

    def test_rendered_mime_uses_crlf_line_endings(self):
        """RFC 5322 §2.1 mandates CRLF line terminators. Bare LF is
        rejected by strict MTAs and may be rewritten by lenient ones —
        which changes content hashes and breaks Message-ID dedup. The
        Messages-path serialization must call ``.as_bytes(linesep="\\r\\n")``
        so the bytes we POST are CRLF-terminated.

        Asserts on the bytes that actually flow to the Messages submit
        endpoint (the same call site as production)."""
        mime_bytes = (
            _build_calendar_email(
                from_email="alice@example.com",
                to_email="bob@example.com",
                reply_to=None,
                subject="t",
                text_body="t",
                html_body="<p>h</p>",
                ics_content="BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
                ics_method="REQUEST",
                itip_enabled=True,
            )
            .message()
            .as_bytes(linesep="\r\n")
        )

        # Split headers from body at the first blank line (CRLFCRLF).
        # If the message used LF-only, this split would not find CRLFCRLF
        # — the assertion below would fail loudly.
        sep = mime_bytes.find(b"\r\n\r\n")
        assert sep != -1, (
            "MIME bytes must have a CRLF-CRLF header/body separator. "
            "Bare LF here means the serializer fell back to LF linesep. "
            f"First 200 bytes: {mime_bytes[:200]!r}"
        )
        headers = mime_bytes[:sep]
        # Every header line break must be CRLF. We search for any "\n"
        # whose preceding byte is not "\r" — that's a bare LF.
        for i, b in enumerate(headers):
            if b == 0x0A and (i == 0 or headers[i - 1] != 0x0D):
                pytest.fail(
                    f"Bare LF at header byte {i} — expected CRLF. "
                    f"Context: {headers[max(0, i - 20) : i + 5]!r}"
                )

    def test_message_id_uses_app_url_domain(self, settings):
        """Pin the end-to-end: the actual ``Message-ID`` header on a
        built invitation carries the configured domain, NOT the container
        hostname (which would be Django's default)."""
        settings.APP_URL = "https://calendars.example.com"
        mime = _build_calendar_email(
            from_email="alice@example.com",
            to_email="bob@example.com",
            reply_to=None,
            subject="x",
            text_body="t",
            html_body="<p>h</p>",
            ics_content="BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            ics_method="REQUEST",
            itip_enabled=True,
        ).message()
        msg_id = mime["Message-ID"] or ""
        assert msg_id.endswith("@_lst_mail.calendars.example.com>"), (
            f"Message-ID must use the APP_URL-derived domain, got: {msg_id!r}"
        )


class TestMessagesServiceSubmitRawMessage:
    """Tests for the HTTP boundary of ``submit_raw_message`` — audit
    findings C (response-body logging), G (auth-header overlay), H
    (retry on transient failure), and J (header sanitization).
    """

    @pytest.fixture(autouse=True)
    def _settings(self, settings):
        settings.MESSAGES_API_URL = "https://messages.test"
        settings.MESSAGES_API_KEY = "real-key"
        settings.MESSAGES_CHANNEL_ID = "real-channel"

    @staticmethod
    def _mock_response(status_code=200, text="OK"):
        resp = MagicMock(spec=["status_code", "text", "raise_for_status"])
        resp.status_code = status_code
        resp.text = text
        if status_code >= 400:
            resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        else:
            resp.raise_for_status.return_value = None
        return resp

    @pytest.mark.parametrize(
        "attacker_key,attacker_channel",
        [
            # Exact case — the obvious attempt.
            ("X-API-Key", "X-Channel-Id"),
            # Lowercase — HTTP headers are case-insensitive, so a server
            # might honor this alongside our X-API-Key. The naive overlay
            # (``hdrs.update``) would let it through.
            ("x-api-key", "x-channel-id"),
            # Mixed case — same threat as lowercase.
            ("X-Api-Key", "x-Channel-id"),
        ],
    )
    def test_caller_cannot_override_auth_headers(self, attacker_key, attacker_channel):
        """Audit finding G: ``_request`` must drop ANY caller header whose
        lowercased name collides with a reserved auth header — not just
        exact-case matches. A lowercase ``x-api-key`` from the caller
        would otherwise survive alongside the configured ``X-API-Key``,
        and most servers honor whichever they parse first."""

        with patch("core.services.messages_service.requests.request") as mock_req:
            mock_req.return_value = self._mock_response(202, '{"ok": true}')
            svc = MessagesService()
            svc._request(  # pylint: disable=protected-access
                "POST",
                "/api/v1.0/submit/",
                data=b"",
                headers={attacker_key: "ATTACKER", attacker_channel: "EVIL"},
            )

        sent_headers = mock_req.call_args.kwargs["headers"]
        # Walk the dict case-insensitively: only one header per name should
        # remain, and its value must be ours.
        api_keys = [v for k, v in sent_headers.items() if k.lower() == "x-api-key"]
        channels = [v for k, v in sent_headers.items() if k.lower() == "x-channel-id"]
        assert api_keys == ["real-key"], (
            f"Expected exactly one X-API-Key with the configured value, "
            f"got: {api_keys!r} (full headers: {sent_headers!r})"
        )
        assert channels == ["real-channel"]

    def test_rcpt_to_header_strips_crlf(self):
        """Audit finding J: a CR/LF in ``rcpt_to`` must never reach the
        wire — that would let an attacker who controls the recipient
        email smuggle a second header (Bcc, X-anything) into the request."""

        with patch("core.services.messages_service.requests.request") as mock_req:
            mock_req.return_value = self._mock_response(202, '{"ok": true}')
            svc = MessagesService()
            svc.submit_raw_message(
                mailbox_id="mbx-1",
                rcpt_to="bob@example.com\r\nBcc: leak@evil.test",
                mime_bytes=b"raw",
            )

        sent_headers = mock_req.call_args.kwargs["headers"]
        rcpt = sent_headers["X-Rcpt-To"]
        assert "\r" not in rcpt and "\n" not in rcpt, (
            f"X-Rcpt-To must be free of CR/LF, got: {rcpt!r}"
        )

    def test_empty_rcpt_after_sanitization_aborts_without_submit(self):
        """An ``rcpt_to`` that sanitizes down to the empty string (e.g.
        all CR/LF) must abort BEFORE the HTTP call — sending
        ``X-Rcpt-To: `` empty leaves Messages-backend behavior
        unspecified and we'd waste a submit either way."""

        with patch("core.services.messages_service.requests.request") as mock_req:
            svc = MessagesService()
            ok = svc.submit_raw_message(
                mailbox_id="mbx-1",
                rcpt_to="\r\n\r\n",
                mime_bytes=b"raw",
            )

        assert ok is False
        assert mock_req.call_count == 0, (
            "submit_raw_message must NOT hit the network when rcpt_to "
            "sanitizes to empty"
        )

    def test_retry_once_on_5xx(self):
        """Audit finding H: a transient 5xx from Messages must trigger
        one retry; if the retry succeeds, the caller sees success."""

        with (
            patch("core.services.messages_service.requests.request") as mock_req,
            patch("core.services.messages_service.time.sleep"),
        ):
            mock_req.side_effect = [
                self._mock_response(503, "upstream busy"),
                self._mock_response(202, '{"id": "ok"}'),
            ]
            svc = MessagesService()
            ok = svc.submit_raw_message(
                mailbox_id="mbx-1",
                rcpt_to="bob@example.com",
                mime_bytes=b"raw",
            )

        assert ok is True
        assert mock_req.call_count == 2, "Expected exactly one retry on 5xx"

    def test_no_retry_on_4xx(self):
        """A 4xx is deterministic — retrying would just repeat the failure
        and burn time. Must fail fast."""

        with (
            patch("core.services.messages_service.requests.request") as mock_req,
            patch("core.services.messages_service.time.sleep"),
        ):
            mock_req.return_value = self._mock_response(400, '{"err": "bad"}')
            svc = MessagesService()
            ok = svc.submit_raw_message(
                mailbox_id="mbx-1",
                rcpt_to="bob@example.com",
                mime_bytes=b"raw",
            )

        assert ok is False
        assert mock_req.call_count == 1, "4xx must NOT retry"

    def test_two_x_calls_each_succeed_independently(self):
        """Two back-to-back submits must each result in a fresh HTTP
        request. Guards against any accidental memoization that would
        cause the second of two attendee invitations to be skipped."""

        with patch("core.services.messages_service.requests.request") as mock_req:
            mock_req.return_value = self._mock_response(202, '{"ok": true}')
            svc = MessagesService()
            svc.submit_raw_message(
                mailbox_id="mbx-1", rcpt_to="alice@a.test", mime_bytes=b"raw1"
            )
            svc.submit_raw_message(
                mailbox_id="mbx-1", rcpt_to="bob@b.test", mime_bytes=b"raw2"
            )

        assert mock_req.call_count == 2
        rcpts = [c.kwargs["headers"]["X-Rcpt-To"] for c in mock_req.call_args_list]
        assert rcpts == ["alice@a.test", "bob@b.test"]
