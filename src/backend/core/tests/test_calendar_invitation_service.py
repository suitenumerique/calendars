"""Tests for ICalendarParser and email template rendering."""

# pylint: disable=missing-function-docstring,protected-access

from django.template.loader import render_to_string

import pytest

from core.services.calendar_invitation_service import (
    CalendarInvitationService,
    ICalendarParser,
)

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
