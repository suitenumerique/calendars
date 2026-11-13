"""Tests for the video link in the ICS of an outgoing invitation."""

import icalendar
import pytest

from core.services.calendar_invitation_service import CalendarInvitationService
from core.services.invitation_video_link import VIDEO_LINK_MARKER, add_video_link

URL = "https://visio.numerique.gouv.fr/abc-defg-hij"
BLOCK = f"{VIDEO_LINK_MARKER}\n{URL}\n{VIDEO_LINK_MARKER}"


def _ics(*vevents: str) -> str:
    events = "".join(
        "BEGIN:VEVENT\r\n"
        "UID:test-123\r\n"
        "DTSTART:20260210T140000Z\r\n"
        "DTEND:20260210T150000Z\r\n"
        "SUMMARY:Team meeting\r\n"
        "ORGANIZER;CN=Alice:mailto:alice@example.com\r\n"
        "ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com\r\n"
        f"{lines}\r\n"
        "END:VEVENT\r\n"
        for lines in vevents
    )
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\nMETHOD:REQUEST\r\n"
        f"{events}END:VCALENDAR\r\n"
    )


def _vevents(icalendar_data: str) -> list[icalendar.Event]:
    return icalendar.Calendar.from_ical(icalendar_data).walk("VEVENT")


def test_adds_link_to_description_location_and_conference():
    """An event with only a URL gets the link in the three properties."""
    (vevent,) = _vevents(add_video_link(_ics(f"URL:{URL}")))

    assert str(vevent["URL"]) == URL
    assert str(vevent["DESCRIPTION"]) == BLOCK
    assert str(vevent["LOCATION"]) == URL
    assert str(vevent["CONFERENCE"]) == URL
    assert vevent["CONFERENCE"].params == {"VALUE": "URI", "FEATURE": "VIDEO"}


def test_keeps_description_and_location():
    """The block goes after the description. A set location does not change."""
    ics = _ics(
        f"URL:{URL}\r\nDESCRIPTION;LANGUAGE=fr:Point hebdo\\, salle 301\r\n"
        "LOCATION:Salle 301"
    )
    (vevent,) = _vevents(add_video_link(ics))

    assert str(vevent["DESCRIPTION"]) == f"Point hebdo, salle 301\n\n{BLOCK}"
    assert vevent["DESCRIPTION"].params == {"LANGUAGE": "fr"}
    assert str(vevent["LOCATION"]) == "Salle 301"


def test_does_not_repeat_a_link_already_in_the_description():
    """A description that contains the link does not change."""
    ics = _ics(f"URL:{URL}\r\nDESCRIPTION:Join here: {URL}")
    (vevent,) = _vevents(add_video_link(ics))

    assert str(vevent["DESCRIPTION"]) == f"Join here: {URL}"


def test_adds_link_to_html_description():
    """The link goes in X-ALT-DESC, before the end of the body."""
    ics = _ics(
        f"URL:{URL}?a=1&b=2\r\n"
        "X-ALT-DESC;FMTTYPE=text/html:<html><body><p>Hello</p></body></html>"
    )
    (vevent,) = _vevents(add_video_link(ics))

    escaped = f"{URL}?a=1&amp;b=2"
    assert str(vevent["X-ALT-DESC"]) == (
        f'<html><body><p>Hello</p><p><a href="{escaped}">{escaped}</a></p>'
        "</body></html>"
    )
    assert vevent["X-ALT-DESC"].params == {"FMTTYPE": "text/html"}


def test_handles_each_occurrence_of_a_recurring_event():
    """The master event and an override each get their own link."""
    other = "https://visio.numerique.gouv.fr/other-room"
    ics = _ics(
        f"RRULE:FREQ=WEEKLY\r\nURL:{URL}",
        f"RECURRENCE-ID:20260217T140000Z\r\nURL:{other}",
    )
    master, override = _vevents(add_video_link(ics))

    assert str(master["LOCATION"]) == URL
    assert str(override["LOCATION"]) == other


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "mailto:bob@example.com", "visio.example.com/room", ""],
)
def test_ignores_a_url_that_is_not_http(url):
    """The data does not change when the URL is not an http(s) link."""
    ics = _ics(f"URL:{url}" if url else "LOCATION:Salle 301")

    assert add_video_link(ics) == ics


def test_returns_invalid_data_unchanged():
    """Data that is not iCalendar does not change."""
    assert add_video_link("not a calendar") == "not a calendar"


@pytest.mark.parametrize("method", ["REQUEST", "CANCEL", "REPLY"])
def test_only_request_attachment_gets_the_link(method):
    """The attachment gets the link for REQUEST only."""
    service = CalendarInvitationService()
    attachment = service._prepare_ics_attachment(  # pylint: disable=protected-access
        _ics(f"URL:{URL}"), method
    )

    assert (VIDEO_LINK_MARKER in attachment) == (method == "REQUEST")
