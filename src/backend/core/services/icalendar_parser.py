"""Parse the iCalendar data of a scheduling message."""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Optional
from urllib.parse import urlparse

from django.utils import timezone

import icalendar

logger = logging.getLogger(__name__)


@dataclass
class EventDetails:  # pylint: disable=too-many-instance-attributes
    """Parsed event details from iCalendar data."""

    uid: str
    summary: str
    description: Optional[str]
    location: Optional[str]
    url: Optional[str]
    dtstart: datetime
    dtend: Optional[datetime]
    organizer_email: str
    organizer_name: Optional[str]
    attendee_email: str
    attendee_name: Optional[str]
    sequence: int
    is_all_day: bool
    raw_icalendar: str
    # The start of the date before the change, when the event is one
    # changed date of a series. It is a date for an all-day date.
    original_start: Optional[date] = None


class ICalendarParser:
    """
    Thin wrapper around the ``icalendar`` library that returns a flat
    ``EventDetails`` dataclass for the email-template / RSVP code paths.

    History: this used to be a hand-rolled regex parser. The regex
    approach was load-bearing on a fragile invariant — that every byte
    reaching it had been re-serialized by sabre/vobject upstream — and
    a security audit (see N1 in the ICS deep-dive) flagged it as a
    line-injection / header-smuggling primitive waiting for the wrong
    code path to feed it raw bytes. The fix is to use a real RFC 5545
    parser. The ``icalendar`` library is already a transitive dependency
    of ``caldav``/``tsdav`` and is used elsewhere in the codebase.
    """

    # URL schemes we are willing to render in invitation email bodies.
    # An ICS ``URL:`` value can be anything per RFC 5545 — including
    # ``javascript:``, ``data:`` or ``vbscript:`` — and we render it
    # straight into an HTML <a href=...> in the calendar_invitation*
    # templates. An attacker who can put an event on your calendar
    # (which is the whole point of an invitation) could otherwise
    # smuggle script-bearing URLs into the recipient's mail client.
    # Most modern clients block ``javascript:`` in href, but the safe
    # default is to allowlist instead of relying on the client.
    _SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto", "tel"})

    @classmethod
    def sanitize_url(cls, raw: Optional[str]) -> Optional[str]:
        """Return ``raw`` only if it parses as a URL with a safe scheme.

        Returns ``None`` for any value whose scheme is not in the
        allowlist (``http``, ``https``, ``mailto``, ``tel``) — including
        scheme-less values, which would otherwise be interpreted as
        same-origin relative URLs by some mail clients.
        """
        if not raw:
            return None
        try:
            parsed = urlparse(raw.strip())
        except ValueError:
            return None
        scheme = (parsed.scheme or "").lower()
        if scheme not in cls._SAFE_URL_SCHEMES:
            logger.info(
                "Dropping ICS URL with disallowed scheme %r from invitation",
                scheme or "(none)",
            )
            return None
        return raw.strip()

    @staticmethod
    def _parse_calendar(icalendar_data: str) -> Optional[icalendar.Calendar]:
        """Wrap ``icalendar.Calendar.from_ical`` with logging."""
        try:
            return icalendar.Calendar.from_ical(icalendar_data)
        except (ValueError, TypeError, KeyError) as exc:
            logger.error("Failed to parse iCalendar data: %s", exc)
            return None

    @staticmethod
    def _first_vevent(cal: icalendar.Calendar):
        """Return the first VEVENT in the calendar (skipping VTIMEZONE)."""
        for component in cal.walk("VEVENT"):
            return component
        return None

    @staticmethod
    def _series_vevent(cal: icalendar.Calendar):
        """Return the VEVENT without RECURRENCE-ID, or else the first VEVENT."""
        for component in cal.walk("VEVENT"):
            if "RECURRENCE-ID" not in component:
                return component
        return ICalendarParser._first_vevent(cal)

    @staticmethod
    def _coerce_aware(value) -> Optional[datetime]:
        """Coerce a date/datetime to a timezone-aware datetime in UTC.

        ``icalendar`` returns naive ``datetime`` for floating times,
        ``date`` for all-day events, and ``datetime`` with ``tzinfo``
        otherwise. The downstream past-event check needs an aware
        datetime; render code only needs a value to format. Anchoring
        all values to UTC keeps comparisons monotonic.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=dt_timezone.utc)
            return value
        if isinstance(value, date):
            # All-day: treat as midnight UTC.
            return datetime(value.year, value.month, value.day, tzinfo=dt_timezone.utc)
        return None

    @staticmethod
    def _is_all_day(value) -> bool:
        """True iff the value is a bare ``date`` (DTSTART;VALUE=DATE)."""
        return isinstance(value, date) and not isinstance(value, datetime)

    @staticmethod
    def _strip_mailto(raw: Optional[str]) -> str:
        if not raw:
            return ""
        return re.sub(r"^mailto:", "", str(raw), flags=re.IGNORECASE).strip()

    @classmethod
    def parse(
        cls,
        icalendar_data: str,
        attendee_email: str,
        recurrence_id: str = "",
        previous_start: str = "",
    ) -> Optional[EventDetails]:
        """Parse iCalendar data and return ``EventDetails``, or None on failure.

        ``attendee_email`` identifies the attendee whose details go into
        ``EventDetails``. ``recurrence_id`` is the RECURRENCE-ID value of
        one date of a series. When the data has an entry for this date,
        the details come from this entry. Otherwise, they come from the
        series, or from the first entry when the data has no series.
        ``previous_start`` is the start of this date before the change, as
        a DATE or UTC DATE-TIME value.
        """
        cal = cls._parse_calendar(icalendar_data)
        if cal is None:
            return None

        occurrence = cls._occurrence(cal, recurrence_id) if recurrence_id else None
        vevent = cls._series_vevent(cal) if occurrence is None else occurrence
        if vevent is None:
            logger.error("No VEVENT component found in iCalendar data")
            return None

        uid = vevent.get("UID")
        if not uid:
            logger.error("VEVENT missing UID")
            return None

        dtstart_prop = vevent.get("DTSTART")
        if dtstart_prop is None:
            logger.error("VEVENT missing DTSTART")
            return None

        dtstart = cls._coerce_aware(dtstart_prop.dt)
        if dtstart is None:
            logger.error("VEVENT DTSTART could not be coerced to a datetime")
            return None

        organizer = vevent.get("ORGANIZER")
        organizer_email, organizer_name = (
            cls._address(organizer) if organizer is not None else ("", None)
        )
        attendee, attendee_name = cls._find_attendee(vevent, attendee_email)

        return EventDetails(
            uid=str(uid),
            summary=str(vevent.get("SUMMARY") or ""),
            description=cls._optional_text(vevent, "DESCRIPTION"),
            location=cls._optional_text(vevent, "LOCATION"),
            url=cls.sanitize_url(cls._optional_text(vevent, "URL")),
            dtstart=dtstart,
            dtend=cls._coerce_aware(cls._end(vevent, dtstart_prop.dt)),
            organizer_email=organizer_email,
            organizer_name=organizer_name,
            attendee_email=attendee,
            attendee_name=attendee_name,
            sequence=cls._sequence(vevent),
            is_all_day=cls._is_all_day(dtstart_prop.dt),
            raw_icalendar=icalendar_data,
            original_start=cls._original_start(occurrence, previous_start, dtstart),
        )

    @staticmethod
    def _end(vevent, start):
        """Return the DTEND value, or the start plus the DURATION, or None.

        The days of the DURATION keep the local time. Its hours, minutes
        and seconds are elapsed time, also across a change of the UTC
        offset.
        """
        dtend = vevent.get("DTEND")
        if dtend is not None:
            return dtend.dt
        duration = vevent.get("DURATION")
        if duration is None:
            return None
        days = timedelta(days=duration.dt.days)
        if not isinstance(start, datetime) or start.tzinfo is None:
            return start + duration.dt
        end = (start + days).astimezone(dt_timezone.utc) + (duration.dt - days)
        return end.astimezone(start.tzinfo)

    @classmethod
    def _original_start(
        cls, occurrence, previous_start: str, dtstart: datetime
    ) -> Optional[date]:
        """Return the start of a date before the change, or None for a series.

        A time is in the time zone of ``dtstart``. An all-day start stays
        a date. Without a valid ``previous_start``, the RECURRENCE-ID
        gives the start.
        """
        if occurrence is None:
            return None
        try:
            value = icalendar.vDDDTypes.from_ical(previous_start)
        except ValueError:
            value = occurrence.decoded("RECURRENCE-ID")
        if cls._is_all_day(value):
            return value
        start = cls._coerce_aware(value)
        return start.astimezone(dtstart.tzinfo) if start else None

    @classmethod
    def _occurrence(cls, cal: icalendar.Calendar, recurrence_id: str):
        """Return the VEVENT with this RECURRENCE-ID value, or None.

        ``recurrence_id`` has no TZID. A value without UTC marker matches
        the same local time in any time zone.
        """
        try:
            wanted = icalendar.vDDDTypes.from_ical(recurrence_id)
        except ValueError:
            return None
        for component in cal.walk("VEVENT"):
            prop = component.get("RECURRENCE-ID")
            # A repeated property gives a list, which matches no date.
            if isinstance(prop, icalendar.vDDDTypes) and cls._same_date(
                prop.dt, wanted
            ):
                return component
        return None

    @classmethod
    def _same_date(cls, value, wanted) -> bool:
        """Tell if a RECURRENCE-ID value names the wanted date."""
        if cls._is_all_day(value) or cls._is_all_day(wanted):
            return (
                cls._is_all_day(value) and cls._is_all_day(wanted) and value == wanted
            )
        if wanted.tzinfo is not None:
            return value.tzinfo is not None and value == wanted
        return value.replace(tzinfo=None) == wanted

    @staticmethod
    def _optional_text(vevent, name: str) -> Optional[str]:
        """Return a text property as a string, or None when it is absent.

        ``icalendar`` decodes the RFC 5545 escapes: ``\\n`` in DESCRIPTION
        becomes a real newline.
        """
        prop = vevent.get(name)
        return str(prop) if prop is not None else None

    @classmethod
    def _address(cls, prop) -> tuple[str, Optional[str]]:
        """Return the email and the CN name of an ORGANIZER or ATTENDEE."""
        cn = prop.params.get("CN") if hasattr(prop, "params") else None
        return cls._strip_mailto(str(prop)), str(cn) if cn else None

    @classmethod
    def _find_attendee(cls, vevent, attendee_email: str) -> tuple[str, Optional[str]]:
        """Return the email and the name of the attendee with this email.

        The email is in lower case. The name is None when no ATTENDEE
        matches, or when it has no CN.
        """
        address = cls._strip_mailto(attendee_email).lower()
        attendees = vevent.get("ATTENDEE")
        if attendees is None:
            return address, None
        if not isinstance(attendees, list):
            attendees = [attendees]
        for attendee in attendees:
            email, name = cls._address(attendee)
            if email.lower() == address:
                return address, name
        return address, None

    @staticmethod
    def _sequence(vevent) -> int:
        """Return the SEQUENCE of the event, or 0 when it is absent or not a number."""
        prop = vevent.get("SEQUENCE")
        try:
            return int(prop) if prop is not None else 0
        except (TypeError, ValueError):
            return 0

    @classmethod
    def is_event_past(cls, icalendar_data: str) -> bool:
        """Return True if the event has already ended.

        Recurring events (with RRULE) are never considered past — the
        recurrence may extend indefinitely. Falls back to DTSTART when
        DTEND is absent.
        """
        cal = cls._parse_calendar(icalendar_data)
        if cal is None:
            return False
        vevent = cls._first_vevent(cal)
        if vevent is None:
            return False
        if vevent.get("RRULE"):
            return False
        prop = vevent.get("DTEND") or vevent.get("DTSTART")
        if prop is None:
            return False
        dt = cls._coerce_aware(prop.dt)
        if dt is None:
            return False
        return dt < timezone.now()

    @classmethod
    def extract_summary(cls, icalendar_data: str) -> str:
        """Return the SUMMARY of the first VEVENT, or '' if none."""
        cal = cls._parse_calendar(icalendar_data)
        if cal is None:
            return ""
        vevent = cls._first_vevent(cal)
        if vevent is None:
            return ""
        return str(vevent.get("SUMMARY") or "")
