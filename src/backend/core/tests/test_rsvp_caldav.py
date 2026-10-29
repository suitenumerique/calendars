"""RSVP link tests against the real CalDAV server.

An RSVP must not change an event that the organizer cancelled or
deleted. It must not add back an attendee that the organizer removed.
"""

# pylint: disable=missing-function-docstring,attribute-defined-outside-init

from datetime import timedelta
from uuid import uuid4

from django.core.signing import TimestampSigner
from django.test import RequestFactory
from django.utils import timezone

import icalendar
import pytest

from core import factories
from core.api.viewsets_rsvp import RSVPConfirmView
from core.services.caldav_service import CalDAVHTTPClient, CalendarService

ATTENDEE = "rsvp-attendee@external-domain.com"


def _fmt(value):
    return value.strftime("%Y%m%dT%H%M%SZ")


def _ics(*vevents):
    """Wrap VEVENT property lines into a VCALENDAR."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//EN"]
    for vevent in vevents:
        lines += ["BEGIN:VEVENT", *vevent, "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def _state(ics, recurrence_id=None):
    """Return the STATUS and the attendee PARTSTAT of one VEVENT.

    `recurrence_id` selects an override; None selects the master.
    """
    for vevent in icalendar.Calendar.from_ical(ics).walk("VEVENT"):
        rid = vevent.get("RECURRENCE-ID")
        if (rid.dt if rid else None) != recurrence_id:
            continue
        attendees = vevent.get("ATTENDEE", [])
        if not isinstance(attendees, list):
            attendees = [attendees]
        partstat = next(
            (
                a.params.get("PARTSTAT")
                for a in attendees
                if str(a).lower() == f"mailto:{ATTENDEE}"
            ),
            None,
        )
        return str(vevent.get("STATUS", "")), partstat
    raise AssertionError(f"No VEVENT for RECURRENCE-ID {recurrence_id}")


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestRSVPDoesNotRestoreEvents:
    """RSVP links leave cancelled or removed events untouched."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.organizer = factories.UserFactory(
            email=f"rsvp-organizer-{uuid4().hex[:8]}@example.com"
        )
        caldav_path = CalendarService().create_calendar(
            self.organizer, name="RSVP guard"
        )
        self.uid = f"rsvp-guard-{uuid4()}"
        self.path = f"{caldav_path}{self.uid}.ics"
        self.start = (timezone.now() + timedelta(days=7)).replace(microsecond=0)

    def _vevent(self, start, *extra, attendee=True):
        lines = [
            f"UID:{self.uid}",
            f"DTSTART:{_fmt(start)}",
            f"DTEND:{_fmt(start + timedelta(hours=1))}",
            "SUMMARY:RSVP guard",
            f"ORGANIZER:mailto:{self.organizer.email}",
            *extra,
        ]
        if attendee:
            lines.append(f"ATTENDEE;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{ATTENDEE}")
        return lines

    def _caldav(self, method, ics=None):
        """Send a raw request, so SabreDAV keeps the VEVENT order as written."""
        return CalDAVHTTPClient().request(
            method,
            self.organizer,
            self.path,
            data=ics.encode() if ics else None,
            content_type="text/calendar" if ics else None,
        )

    def _rsvp(self):
        token = TimestampSigner(salt="rsvp").sign_object(
            {
                "u": self.uid,
                "e": ATTENDEE,
                "o": self.organizer.email,
                "g": str(self.organizer.organization_id),
                "a": "accepted",
            }
        )
        request = RequestFactory().post("/rsvp/", {"token": token})
        return RSVPConfirmView.as_view()(request)

    def test_cancelled_event_is_not_updated(self):
        self._caldav("PUT", _ics(self._vevent(self.start, "STATUS:CANCELLED")))

        response = self._rsvp()

        assert response.status_code == 400
        assert "cancelled by the organizer" in response.content.decode()
        assert _state(self._caldav("GET").text) == ("CANCELLED", "NEEDS-ACTION")

    def test_deleted_event_is_not_recreated(self):
        self._caldav("PUT", _ics(self._vevent(self.start)))
        self._caldav("DELETE")

        response = self._rsvp()

        assert response.status_code == 400
        assert "no longer exists" in response.content.decode()
        assert self._caldav("GET").status_code == 404

    def test_removed_attendee_is_not_added_back(self):
        self._caldav("PUT", _ics(self._vevent(self.start, attendee=False)))

        response = self._rsvp()

        assert response.status_code == 400
        assert "not listed as an attendee" in response.content.decode()
        assert _state(self._caldav("GET").text) == ("", None)

    def test_cancelled_occurrence_stays_cancelled(self):
        cancelled = self.start + timedelta(days=1)
        # The override comes first. The RSVP must still target the master.
        override = self._vevent(
            cancelled, f"RECURRENCE-ID:{_fmt(cancelled)}", "STATUS:CANCELLED"
        )
        master = self._vevent(self.start, "RRULE:FREQ=DAILY;COUNT=3")
        assert self._caldav("PUT", _ics(override, master)).status_code == 201

        response = self._rsvp()

        assert response.status_code == 200
        stored = self._caldav("GET").text
        assert _state(stored) == ("", "ACCEPTED")
        assert _state(stored, cancelled) == ("CANCELLED", "NEEDS-ACTION")
