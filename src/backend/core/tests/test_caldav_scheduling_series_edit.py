"""Tests for the messages of an edit of a whole recurring series."""

# pylint: disable=no-member

import re
import threading
import time
from datetime import datetime

import icalendar
import pytest

from caldav.lib.error import NotFoundError
from core import factories
from core.services.caldav_service import CalendarService
from core.tests.test_caldav_scheduling import _wait_for_callbacks, create_test_server

REMOVED = "removed@external-a.test"
KEPT = "kept@external-b.test"
ADDED = "added@external-c.test"


def _vevent(organizer, attendees, *lines):
    """Give a VEVENT of a weekly series on Mondays from January 4, 2027."""
    return "\n".join(
        [
            "BEGIN:VEVENT",
            "UID:series-edit",
            *lines,
            "SUMMARY:Weekly event",
            f"ORGANIZER;CN=Organizer:mailto:{organizer}",
            *(f"ATTENDEE;RSVP=TRUE:mailto:{email}" for email in attendees),
            "END:VEVENT",
        ]
    )


def _master(organizer, attendees, rrule="RRULE:FREQ=WEEKLY;COUNT=3", sequence=0):
    return _vevent(
        organizer,
        attendees,
        "DTSTART:20270104T090000Z",
        "DTEND:20270104T100000Z",
        rrule,
        f"SEQUENCE:{sequence}",
    )


def _moved_date(organizer, attendees, sequence=0):
    """Give the override that moves January 11 to 14:00."""
    return _vevent(
        organizer,
        attendees,
        "RECURRENCE-ID:20270111T090000Z",
        "DTSTART:20270111T140000Z",
        "DTEND:20270111T150000Z",
        f"SEQUENCE:{sequence}",
    )


def _send_edit(organizer, stored, new, stored_messages=2):
    """Store an event, then write its new version.

    Return the (recipient, method, body) of each message of the new version.
    """
    service = CalendarService()
    caldav_path = service.create_calendar(organizer, name="Series", color="#00aaaa")

    server, _port, callback_data = create_test_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.5)

    try:
        client = service._get_client(organizer)  # pylint: disable=protected-access
        calendar_url = service._calendar_url(caldav_path)  # pylint: disable=protected-access
        uid = f"series-edit-{datetime.now().timestamp()}"
        event_url = (
            f"{str(client.calendar(url=calendar_url).url).rstrip('/')}/{uid}.ics"
        )

        def put(components):
            body = "\n".join(
                ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//EN"]
                + components
                + ["END:VCALENDAR"]
            ).replace("UID:series-edit\n", f"UID:{uid}\n")
            response = client.put(event_url, body, {"Content-Type": "text/calendar"})
            assert response.status < 300

        put(stored)
        _wait_for_callbacks(callback_data, expected_count=stored_messages)
        callback_data["requests"] = []

        put(new)
        _wait_for_callbacks(callback_data, expected_count=3, timeout=1.0)
    except NotFoundError:
        pytest.skip("Calendar not found - CalDAV server may not be running")
    finally:
        server.shutdown()
        server.server_close()

    return [
        (
            re.sub(r"(?i)^mailto:", "", r["headers"].get("X-LS-Recipient", "")),
            r["headers"].get("X-LS-Method"),
            r["body"],
        )
        for r in callback_data["requests"]
    ]


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestCalDAVSeriesEdit:
    """Messages of an edit of all the dates of a series."""

    def test_attendee_change_of_all_dates_includes_the_moved_date(self):
        """The edit removes an attendee and adds another to the master and
        to the moved date. The removed attendee gets a cancellation of the
        whole event. The added attendee gets all the dates, with no EXDATE."""
        organizer = factories.UserFactory(email="organizer-series-edit@example.com")
        email = organizer.email

        messages = _send_edit(
            organizer,
            [_master(email, [REMOVED, KEPT]), _moved_date(email, [REMOVED, KEPT])],
            [
                _master(email, [KEPT, ADDED], sequence=1),
                _moved_date(email, [KEPT, ADDED], sequence=1),
            ],
        )

        by_recipient = {
            recipient: (method, body) for recipient, method, body in messages
        }
        method, body = by_recipient[REMOVED]
        assert method == "CANCEL"
        assert "RECURRENCE-ID" not in body

        method, body = by_recipient[ADDED]
        assert method == "REQUEST"
        assert "EXDATE" not in body
        moved = next(
            vevent
            for vevent in icalendar.Calendar.from_ical(body).walk("VEVENT")
            if vevent.get("RECURRENCE-ID")
        )
        assert moved["RECURRENCE-ID"].to_ical() == b"20270111T090000Z"
        assert moved["DTSTART"].to_ical() == b"20270111T140000Z"
        assert moved["DTEND"].to_ical() == b"20270111T150000Z"

    def test_truncated_series_is_an_update(self):
        """A "this and future" edit ends the old series and increments its
        SEQUENCE. The guest gets a REQUEST with this SEQUENCE: the email is
        an update."""
        organizer = factories.UserFactory(email="organizer-series-cut@example.com")
        email = organizer.email

        messages = _send_edit(
            organizer,
            [_master(email, [KEPT], rrule="RRULE:FREQ=WEEKLY")],
            [
                _master(
                    email,
                    [KEPT],
                    rrule="RRULE:FREQ=WEEKLY;UNTIL=20270110T235959Z",
                    sequence=1,
                )
            ],
            stored_messages=1,
        )

        assert [(r, m) for r, m, _body in messages] == [(KEPT, "REQUEST")]
        assert "SEQUENCE:1" in messages[0][2]
