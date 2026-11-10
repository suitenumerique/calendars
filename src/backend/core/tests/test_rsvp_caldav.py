"""RSVP link tests against the real CalDAV server.

An RSVP must not change an event that the organizer cancelled or
deleted. It must not add back an attendee that the organizer removed.
"""

# pylint: disable=missing-function-docstring,attribute-defined-outside-init

from datetime import timedelta
from uuid import uuid4
from xml.etree import ElementTree as ET

from django.core.signing import TimestampSigner
from django.test import RequestFactory
from django.utils import timezone

import icalendar
import pytest

from core import factories
from core.api.viewsets_rsvp import RSVPConfirmView
from core.services.caldav_service import CalDAVHTTPClient, CalendarService

ATTENDEE = "rsvp-attendee@external-domain.com"

EXPAND_QUERY = """<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <C:calendar-data><C:expand start="{start}" end="{end}"/></C:calendar-data>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{start}" end="{end}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""


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
        request = RequestFactory(HTTP_ACCEPT_LANGUAGE="en").post(
            "/rsvp/", {"token": token}
        )
        return RSVPConfirmView.as_view()(request)

    def test_cancelled_event_is_not_updated(self):
        self._caldav("PUT", _ics(self._vevent(self.start, "STATUS:CANCELLED")))

        response = self._rsvp()

        assert response.status_code == 400
        assert "cancelled by the organizer" in response.content.decode()
        assert _state(self._caldav("GET").text) == ("CANCELLED", "NEEDS-ACTION")

    def test_deleted_event_is_not_recreated(self):
        assert self._caldav("PUT", _ics(self._vevent(self.start))).status_code == 201
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


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestStaleAttendeeWrite:
    """A CalDAV client cannot answer from a stale copy of an invitation.

    Here the attendee is a user of the server, so SabreDAV delivers the
    invitation to the calendar of the attendee. The attendee reads that
    copy, the organizer then changes the event, and the attendee writes
    the old copy back with its old ETag. The If-Match check refuses the
    write, so the change of the organizer stays on both copies.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        suffix = uuid4().hex[:8]
        self.organizer = factories.UserFactory(email=f"stale-org-{suffix}@example.com")
        self.attendee = factories.UserFactory(email=f"stale-att-{suffix}@example.com")
        service = CalendarService()
        service.ensure_default_calendar(self.attendee)
        self.calendar = service.create_calendar(self.organizer, name="Stale")
        self.uid = f"stale-{uuid4()}"
        self.start = (timezone.now() + timedelta(days=7)).replace(microsecond=0)

    def _ics(self, *extra, attendee=True):
        lines = [
            f"UID:{self.uid}",
            f"DTSTART:{_fmt(self.start)}",
            f"DTEND:{_fmt(self.start + timedelta(hours=1))}",
            "SUMMARY:Stale copy",
            f"ORGANIZER:mailto:{self.organizer.email}",
            *extra,
        ]
        if attendee:
            lines.append(
                f"ATTENDEE;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{self.attendee.email}"
            )
        return _ics(lines)

    def _organizer_put(self, ics):
        response = CalDAVHTTPClient().request(
            "PUT",
            self.organizer,
            f"{self.calendar}{self.uid}.ics",
            data=ics.encode(),
            content_type="text/calendar",
        )
        assert response.status_code in (201, 204)

    def _attendee_copy(self):
        _, href, _ = CalDAVHTTPClient().find_event_by_uid(self.attendee, self.uid)
        assert href, "SabreDAV did not deliver the invitation to the attendee"
        path = href.removeprefix(CalDAVHTTPClient.BASE_URI_PATH)
        response = CalDAVHTTPClient().request("GET", self.attendee, path)
        assert response.status_code == 200
        return path, response.text, response.headers["ETag"]

    def _status(self, ics):
        return str(
            icalendar.Calendar.from_ical(ics).walk("VEVENT")[0].get("STATUS", "")
        )

    @pytest.mark.parametrize(
        ("change", "keep_attendee", "organizer_status"),
        [
            pytest.param(["STATUS:CANCELLED"], True, "CANCELLED", id="cancelled"),
            pytest.param([], False, "", id="attendee-removed"),
        ],
    )
    def test_stale_attendee_put_is_refused(
        self, change, keep_attendee, organizer_status
    ):
        self._organizer_put(self._ics())
        path, stale, etag = self._attendee_copy()

        self._organizer_put(self._ics("SEQUENCE:1", *change, attendee=keep_attendee))
        assert self._status(self._attendee_copy()[1]) == "CANCELLED"

        accepted = stale.replace("PARTSTAT=NEEDS-ACTION", "PARTSTAT=ACCEPTED")
        response = CalDAVHTTPClient().request(
            "PUT",
            self.attendee,
            path,
            data=accepted.encode(),
            content_type="text/calendar",
            extra_headers={"If-Match": etag},
        )

        assert response.status_code == 412
        attendee_copy = self._attendee_copy()[1]
        assert self._status(attendee_copy) == "CANCELLED"
        assert "PARTSTAT=ACCEPTED" not in attendee_copy
        organizer_copy = (
            CalDAVHTTPClient()
            .request("GET", self.organizer, f"{self.calendar}{self.uid}.ics")
            .text
        )
        assert self._status(organizer_copy) == organizer_status
        assert "PARTSTAT=ACCEPTED" not in organizer_copy


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestOccurrenceOverride:
    """A new override must not add an EXDATE to the master.

    An attendee answers one occurrence with an override in its copy.
    SabreDAV sends a REPLY to the organizer and updates the copy of the
    organizer. A new EXDATE in the copy of the attendee reads as a decline
    of the occurrence.

    An organizer moves one occurrence with an override of the same kind.
    The expansion of the server must show the occurrence one time, at the
    new time.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        suffix = uuid4().hex[:8]
        self.organizer = factories.UserFactory(email=f"occ-org-{suffix}@example.com")
        self.attendee = factories.UserFactory(email=f"occ-att-{suffix}@example.com")
        service = CalendarService()
        service.ensure_default_calendar(self.attendee)
        self.calendar = service.create_calendar(self.organizer, name="Occurrence")
        self.uid = f"occ-{uuid4()}"
        self.start = (timezone.now() + timedelta(days=7)).replace(
            microsecond=0, second=0
        )
        self.occurrence = self.start + timedelta(days=2)

    def _vevent(self, start, partstat, *extra):
        return [
            f"UID:{self.uid}",
            "DTSTAMP:20260101T000000Z",
            f"DTSTART:{_fmt(start)}",
            f"DTEND:{_fmt(start + timedelta(hours=1))}",
            "SUMMARY:Daily",
            f"ORGANIZER:mailto:{self.organizer.email}",
            f"ATTENDEE;PARTSTAT={partstat};RSVP=TRUE:mailto:{self.attendee.email}",
            *extra,
        ]

    def _organizer_put(self, *vevents):
        response = CalDAVHTTPClient().request(
            "PUT",
            self.organizer,
            f"{self.calendar}{self.uid}.ics",
            data=_ics(*vevents).encode(),
            content_type="text/calendar",
        )
        assert response.status_code in (201, 204)

    def _organizer_copy(self):
        response = CalDAVHTTPClient().request(
            "GET", self.organizer, f"{self.calendar}{self.uid}.ics"
        )
        assert response.status_code == 200
        return response.text

    def _attendee_href(self):
        _, href, _ = CalDAVHTTPClient().find_event_by_uid(self.attendee, self.uid)
        assert href, "SabreDAV did not deliver the invitation to the attendee"
        return href

    def _occurrences(self, user, calendar):
        """Return the start and the STATUS of each occurrence.

        The server expands the series, as for the calendar view.
        """
        response = CalDAVHTTPClient().request(
            "REPORT",
            user,
            calendar,
            data=EXPAND_QUERY.format(
                start=_fmt(self.start - timedelta(days=1)),
                end=_fmt(self.start + timedelta(days=6)),
            ).encode(),
            content_type="application/xml",
            extra_headers={"Depth": "1"},
        )
        assert response.status_code == 207
        return sorted(
            (vevent["DTSTART"].dt, str(vevent.get("STATUS", "")))
            for data in ET.fromstring(response.content).iter(
                "{urn:ietf:params:xml:ns:caldav}calendar-data"
            )
            for vevent in icalendar.Calendar.from_ical(data.text).walk("VEVENT")
        )

    def _partstat(self, ics):
        for vevent in icalendar.Calendar.from_ical(ics).walk("VEVENT"):
            rid = vevent.get("RECURRENCE-ID")
            if not rid or rid.dt != self.occurrence:
                continue
            attendees = vevent.get("ATTENDEE", [])
            if not isinstance(attendees, list):
                attendees = [attendees]
            return next(
                str(a.params.get("PARTSTAT"))
                for a in attendees
                if str(a).lower() == f"mailto:{self.attendee.email}"
            )
        raise AssertionError("No override for the occurrence")

    @pytest.mark.parametrize(
        ("exdate", "expected"),
        [
            pytest.param(False, "ACCEPTED", id="override-only"),
            pytest.param(True, "DECLINED", id="override-and-exdate"),
        ],
    )
    def test_reply_to_one_occurrence(self, exdate, expected):
        self._organizer_put(
            self._vevent(self.start, "NEEDS-ACTION", "RRULE:FREQ=DAILY;COUNT=5")
        )
        path = self._attendee_href().removeprefix(CalDAVHTTPClient.BASE_URI_PATH)

        master = ["RRULE:FREQ=DAILY;COUNT=5"]
        if exdate:
            master.append(f"EXDATE:{_fmt(self.occurrence)}")
        override = [f"RECURRENCE-ID:{_fmt(self.occurrence)}", "SEQUENCE:1"]
        response = CalDAVHTTPClient().request(
            "PUT",
            self.attendee,
            path,
            data=_ics(
                self._vevent(self.start, "NEEDS-ACTION", *master),
                self._vevent(self.occurrence, "ACCEPTED", *override),
            ).encode(),
            content_type="text/calendar",
        )

        assert response.status_code in (201, 204)
        assert self._partstat(self._organizer_copy()) == expected

    def test_organizer_moves_one_occurrence(self):
        master = self._vevent(self.start, "NEEDS-ACTION", "RRULE:FREQ=DAILY;COUNT=5")
        self._organizer_put(master)

        moved = self.occurrence + timedelta(hours=3)
        override = [f"RECURRENCE-ID:{_fmt(self.occurrence)}", "SEQUENCE:1"]
        self._organizer_put(master, self._vevent(moved, "NEEDS-ACTION", *override))

        # No occurrence at the old time, and no cancelled occurrence.
        expected = sorted(
            (start, "")
            for start in (
                *(self.start + timedelta(days=day) for day in (0, 1, 3, 4)),
                moved,
            )
        )
        assert self._occurrences(self.organizer, self.calendar) == expected
        attendee_calendar = self._attendee_href().rsplit("/", 1)[0] + "/"
        assert self._occurrences(self.attendee, attendee_calendar) == expected
