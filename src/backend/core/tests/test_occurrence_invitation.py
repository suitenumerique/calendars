"""Tests for the email about a change to one date of a series."""

# pylint: disable=missing-function-docstring

import re
from datetime import UTC, date, datetime
from unittest.mock import patch
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from django.core.signing import TimestampSigner

import pytest

from core.services.calendar_invitation_service import (
    CalendarInvitationService,
    ICalendarParser,
)

# A weekly series on Mondays from January 4, 2027, 09:00 to 10:00 UTC.
# January 11 moves to Tuesday 12, 14:00. January 18 moves one hour later.
ICS_SERIES = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:series-1
DTSTART:20270104T090000Z
DTEND:20270104T100000Z
RRULE:FREQ=WEEKLY;COUNT=4
SUMMARY:Weekly meeting
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:0
END:VEVENT
BEGIN:VEVENT
UID:series-1
RECURRENCE-ID:20270111T090000Z
DTSTART:20270112T140000Z
DTEND:20270112T150000Z
SUMMARY:Weekly meeting
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:1
END:VEVENT
BEGIN:VEVENT
UID:series-1
RECURRENCE-ID:20270118T090000Z
DTSTART:20270118T100000Z
DTEND:20270118T110000Z
SUMMARY:Weekly meeting
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:1
END:VEVENT
END:VCALENDAR"""

# January 11 keeps its time and gets a location.
ICS_LOCATION = ICS_SERIES.replace(
    "DTSTART:20270112T140000Z\nDTEND:20270112T150000Z\n",
    "DTSTART:20270111T090000Z\nDTEND:20270111T100000Z\nLOCATION:Room 2\n",
)


def _send_request(icalendar_data, **kwargs):
    with patch.object(
        CalendarInvitationService, "_send_email", return_value=True
    ) as mock_send_email:
        result = CalendarInvitationService().send_invitation(
            sender_email="mailto:alice@example.com",
            recipient_email="mailto:bob@example.com",
            method="REQUEST",
            icalendar_data=icalendar_data,
            **kwargs,
        )
    assert result is True
    return mock_send_email.call_args.kwargs


class TestParseChangedDate:
    """The parser takes the entry of the changed date."""

    def test_takes_the_entry_of_the_date(self):
        event = ICalendarParser.parse(
            ICS_SERIES, "bob@example.com", recurrence_id="20270118T090000Z"
        )

        assert event.dtstart == datetime(2027, 1, 18, 10, tzinfo=UTC)
        assert event.dtend == datetime(2027, 1, 18, 11, tzinfo=UTC)
        assert event.original_start == datetime(2027, 1, 18, 9, tzinfo=UTC)
        assert event.sequence == 1

    def test_takes_the_series_without_a_date(self):
        event = ICalendarParser.parse(ICS_SERIES, "bob@example.com")

        assert event.dtstart == datetime(2027, 1, 4, 9, tzinfo=UTC)
        assert event.original_start is None

    def test_takes_the_series_for_an_unknown_date(self):
        event = ICalendarParser.parse(
            ICS_SERIES, "bob@example.com", recurrence_id="20270125T090000Z"
        )

        assert event.dtstart == datetime(2027, 1, 4, 9, tzinfo=UTC)
        assert event.original_start is None

    def test_matches_a_local_time(self):
        ics = ICS_SERIES.replace(
            "RECURRENCE-ID:20270111T090000Z",
            "RECURRENCE-ID;TZID=Europe/Paris:20270111T100000",
        )

        event = ICalendarParser.parse(
            ics, "bob@example.com", recurrence_id="20270111T100000"
        )

        assert event.dtstart == datetime(2027, 1, 12, 14, tzinfo=UTC)
        assert event.original_start == datetime(2027, 1, 11, 9, tzinfo=UTC)

    def test_matches_a_utc_time_zone(self):
        ics = ICS_SERIES.replace(
            "RECURRENCE-ID:20270111T090000Z",
            "RECURRENCE-ID;TZID=UTC:20270111T090000",
        )

        event = ICalendarParser.parse(
            ics, "bob@example.com", recurrence_id="20270111T090000"
        )

        assert event.dtstart == datetime(2027, 1, 12, 14, tzinfo=UTC)

    def test_keeps_a_date_and_a_time_apart(self):
        event = ICalendarParser.parse(
            ICS_SERIES, "bob@example.com", recurrence_id="20270111"
        )

        assert event.original_start is None

    def test_takes_the_series_after_a_date(self):
        series_end = ICS_SERIES.index(
            "BEGIN:VEVENT", 1 + ICS_SERIES.index("BEGIN:VEVENT")
        )
        start = ICS_SERIES.index("BEGIN:VEVENT")
        ics = (
            ICS_SERIES[:start]
            + ICS_SERIES[series_end:].removesuffix("END:VCALENDAR")
            + ICS_SERIES[start:series_end]
            + "END:VCALENDAR"
        )

        event = ICalendarParser.parse(ics, "bob@example.com")

        assert event.dtstart == datetime(2027, 1, 4, 9, tzinfo=UTC)

    def test_takes_the_end_from_the_duration(self):
        ics = ICS_SERIES.replace("DTEND:20270112T150000Z", "DURATION:PT2H")

        event = ICalendarParser.parse(
            ics, "bob@example.com", recurrence_id="20270111T090000Z"
        )

        assert event.dtend == datetime(2027, 1, 12, 16, tzinfo=UTC)

    @pytest.mark.parametrize(
        "start, duration, end",
        [
            ("20270328T013000", "PT2H", datetime(2027, 3, 28, 4, 30)),
            ("20270327T120000", "P1D", datetime(2027, 3, 28, 12)),
        ],
    )
    def test_takes_the_duration_across_a_time_change(self, start, duration, end):
        # On March 28, 2027, Paris skips from 02:00 to 03:00. Hours are
        # elapsed time, days keep the local time.
        ics = ICS_SERIES.replace(
            "DTSTART:20270112T140000Z\nDTEND:20270112T150000Z",
            f"DTSTART;TZID=Europe/Paris:{start}\nDURATION:{duration}",
        )

        event = ICalendarParser.parse(
            ics, "bob@example.com", recurrence_id="20270111T090000Z"
        )

        assert event.dtend == end.replace(tzinfo=ZoneInfo("Europe/Paris"))

    def test_takes_the_previous_start(self):
        event = ICalendarParser.parse(
            ICS_SERIES,
            "bob@example.com",
            recurrence_id="20270118T090000Z",
            previous_start="20270118T093000Z",
        )

        assert event.original_start == datetime(2027, 1, 18, 9, 30, tzinfo=UTC)

    def test_keeps_an_all_day_previous_start(self):
        event = ICalendarParser.parse(
            ICS_SERIES,
            "bob@example.com",
            recurrence_id="20270111T090000Z",
            previous_start="20270111",
        )

        assert event.original_start == date(2027, 1, 11)

    def test_gives_the_previous_start_in_the_time_zone_of_the_date(self):
        ics = ICS_SERIES.replace(
            "DTSTART:20270112T140000Z\nDTEND:20270112T150000Z",
            "DTSTART;TZID=Europe/Paris:20270112T150000\n"
            "DTEND;TZID=Europe/Paris:20270112T160000",
        )

        event = ICalendarParser.parse(
            ics,
            "bob@example.com",
            recurrence_id="20270111T090000Z",
            previous_start="20270111T090000Z",
        )

        assert event.original_start.tzinfo == ZoneInfo("Europe/Paris")
        assert event.original_start.hour == 10


@pytest.mark.django_db
class TestChangedDateEmail:
    """The email about a changed date shows this date."""

    def test_shows_the_old_and_the_new_date(self):
        kwargs = _send_request(ICS_SERIES, recurrence_id="20270111T090000Z")

        assert kwargs["subject"] == "Invitation modifiée : Weekly meeting"
        for body in (kwargs["text_body"], kwargs["html_body"]):
            assert "Était prévu le" in body
            assert "lundi 11 janvier 2027 · 09:00" in body
            assert "mardi 12 janvier 2027" in body
            assert "14:00 - 15:00" in body
            assert "lundi 4 janvier" not in body
        assert 'line-through;">lundi 11 janvier 2027 · 09:00' in kwargs["html_body"]

    def test_is_an_update_with_a_series_sequence_of_zero(self):
        kwargs = _send_request(ICS_SERIES, recurrence_id="20270118T090000Z")

        assert kwargs["subject"].startswith("Invitation modifiée")
        assert "lundi 18 janvier 2027 · 09:00" in kwargs["text_body"]
        assert "10:00 - 11:00" in kwargs["text_body"]

    def test_shows_no_old_date_when_the_time_stays(self):
        kwargs = _send_request(ICS_LOCATION, recurrence_id="20270111T090000Z")

        assert kwargs["subject"].startswith("Invitation modifiée")
        assert "Room 2" in kwargs["text_body"]
        assert "lundi 11 janvier 2027 09:00 - 10:00" in kwargs["text_body"]
        for body in (kwargs["text_body"], kwargs["html_body"]):
            assert "Était prévu le" not in body

    def test_shows_a_move_in_the_repeated_hour(self):
        # On October 31, 2027, 02:30 in Paris happens twice. The date
        # moves from the second 02:30 (01:30 UTC) to the first one.
        ics = ICS_SERIES.replace(
            "DTSTART:20270118T100000Z\nDTEND:20270118T110000Z",
            "DTSTART;TZID=Europe/Paris:20271031T023000\n"
            "DTEND;TZID=Europe/Paris:20271031T033000",
        )

        kwargs = _send_request(
            ics, recurrence_id="20270118T090000Z", previous_start="20271031T013000Z"
        )

        assert "Était prévu le" in kwargs["text_body"]

    def test_shows_the_previous_start_of_a_moved_date(self):
        kwargs = _send_request(
            ICS_SERIES,
            recurrence_id="20270118T090000Z",
            previous_start="20270118T093000Z",
        )

        assert "lundi 18 janvier 2027 · 09:30" in kwargs["text_body"]

    def test_shows_an_all_day_previous_start_without_a_time(self):
        kwargs = _send_request(
            ICS_SERIES, recurrence_id="20270111T090000Z", previous_start="20270111"
        )

        assert "lundi 11 janvier 2027\nQuand" in kwargs["text_body"]
        assert 'line-through;">lundi 11 janvier 2027<' in kwargs["html_body"]

    def test_shows_no_old_date_when_a_moved_date_keeps_its_time(self):
        kwargs = _send_request(
            ICS_SERIES,
            recurrence_id="20270118T090000Z",
            previous_start="20270118T100000Z",
        )

        assert kwargs["subject"].startswith("Invitation modifiée")
        for body in (kwargs["text_body"], kwargs["html_body"]):
            assert "Était prévu le" not in body

    def test_shows_the_series_without_a_date(self):
        kwargs = _send_request(ICS_SERIES)

        assert kwargs["subject"] == "Invitation : Weekly meeting"
        assert "lundi 4 janvier 2027" in kwargs["text_body"]
        assert "Était prévu le" not in kwargs["text_body"]

    def test_new_attendee_gets_an_invitation_for_the_date(self):
        kwargs = _send_request(
            ICS_SERIES, recurrence_id="20270111T090000Z", is_new_attendee=True
        )

        assert kwargs["subject"] == "Invitation : Weekly meeting"
        assert "mardi 12 janvier 2027" in kwargs["text_body"]
        for body in (kwargs["text_body"], kwargs["html_body"]):
            assert "Était prévu le" not in body

    def test_answer_links_are_for_the_event(self):
        kwargs = _send_request(ICS_SERIES, recurrence_id="20270111T090000Z")

        tokens = re.findall(r"/rsvp/\?t=([^\s\"&]+)", kwargs["text_body"])
        assert len(tokens) == 3
        for token in tokens:
            data = TimestampSigner(salt="rsvp").unsign_object(unquote(token))
            assert data["u"] == "series-1"
            assert set(data) == {"u", "e", "o", "g", "a"}
