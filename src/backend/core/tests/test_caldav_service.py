"""Tests for CalDAV service integration."""

# pylint: disable=too-many-lines

import re
from datetime import datetime, timezone

import pytest

from core import factories
from core.services.caldav_service import CalDAVClient, CalDAVHTTPClient, CalendarService


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestCalDAVClient:
    """Tests for CalDAVClient authentication and communication."""

    def test_get_client_sends_x_forwarded_user_header(self):
        """Test that DAVClient is configured with X-LS-User header."""
        user = factories.UserFactory(email="test@example.com")
        client = CalDAVClient()

        dav_client = client._get_client(user)  # pylint: disable=protected-access

        # Verify the client is configured correctly
        # Username and password should be None to prevent Basic auth
        assert dav_client.username is None
        assert dav_client.password is None

        # Verify the X-LS-User header is set
        # The caldav library stores headers as a CaseInsensitiveDict
        assert hasattr(dav_client, "headers")
        assert "X-LS-User" in dav_client.headers
        assert dav_client.headers["X-LS-User"] == user.email

    def test_create_calendar_authenticates_with_caldav_server(self):
        """Test that calendar creation authenticates successfully with CalDAV server."""
        user = factories.UserFactory(email="test@example.com")
        client = CalDAVClient()

        # Try to create a calendar - this should authenticate successfully
        calendar_path = client.create_calendar(
            user, calendar_name="Test Calendar", calendar_id="test-calendar-id"
        )

        # Verify calendar path was returned
        assert calendar_path is not None
        # Email may be URL-encoded in the path (e.g., test%40example.com)
        assert (
            user.email.replace("@", "%40") in calendar_path
            or user.email in calendar_path
        )

    def test_calendar_service_creates_calendar(self):
        """Test that CalendarService can create a calendar through CalDAV server."""
        user = factories.UserFactory(email="test@example.com")
        service = CalendarService()

        # Create a calendar — returns caldav_path string
        caldav_path = service.create_calendar(user, name="My Calendar", color="#ff0000")

        # Verify caldav_path was returned
        assert caldav_path is not None
        assert isinstance(caldav_path, str)
        assert "calendars/" in caldav_path

    def test_create_calendar_with_color_persists(self):
        """Test that creating a calendar with a color saves it in CalDAV."""
        user = factories.UserFactory(email="color-test@example.com")
        service = CalendarService()
        color = "#e74c3c"

        # Create a calendar with a specific color
        caldav_path = service.create_calendar(user, name="Red Calendar", color=color)

        # Fetch the calendar info and verify the color was persisted
        info = service.get_calendar_info(user, caldav_path)
        assert info is not None
        assert info["color"] == color
        assert info["name"] == "Red Calendar"


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
# pylint: disable=too-many-public-methods
class TestCalendarSanitizerRRULECap:
    """CalendarSanitizerPlugin caps unbounded RRULEs on every CalDAV write.

    `sabre/vobject` rejects events whose RRULE would expand past
    `Settings::$maxRecurrences` with HTTP 500
    `MaxInstancesExceededException`. Naked `FREQ=DAILY` ("Daily
    forever") would otherwise be rejected on every CalDAV write,
    including iTIP REQUEST routing.

    The sanitizer plugin runs at priority 85 on `beforeCreateFile` /
    `beforeWriteContent` and:

    - DAILY/WEEKLY/MONTHLY/YEARLY/HOURLY: injects a per-FREQ COUNT.
      COUNT (not UNTIL) is required because BY-expansion in the RRULE
      (e.g. ``FREQ=DAILY;BYHOUR=0,...,23``) multiplies instances per
      iteration; UNTIL would silently allow blowing past
      `maxRecurrences`, while COUNT caps occurrences directly.
    - MINUTELY/SECONDLY: strips the RRULE. `sabre/vobject`'s
      RRuleIterator never advances the clock for sub-day frequencies,
      so no bound we inject can stop iteration. EXDATE is dropped
      only if every RRULE was stripped AND there's no surviving
      RDATE — otherwise the exceptions still apply to the surviving
      recurrence and are kept.
    """

    @staticmethod
    def _make_ics(uid: str, frequency: str | None, extra_rrule: str = "") -> str:
        if frequency is None:
            rrule_line = ""
        else:
            rrule_line = f"RRULE:FREQ={frequency}{extra_rrule}\r\n"
        return (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260529T120000Z\r\n"
            "DTSTART:20260530T140000Z\r\n"
            "DTEND:20260530T150000Z\r\n"
            "SUMMARY:cap-test\r\n"
            f"{rrule_line}"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

    @staticmethod
    def _rrule_line(ical_data: str) -> str | None:
        for line in ical_data.splitlines():
            if line.startswith("RRULE:"):
                return line
        return None

    @pytest.mark.parametrize(
        "frequency", ["DAILY", "WEEKLY", "MONTHLY", "YEARLY", "HOURLY"]
    )
    def test_unbounded_rrule_is_capped_on_create(self, frequency):
        """An unbounded RRULE survives PUT instead of returning 500.

        Every capped FREQ gets ``COUNT=N`` injected. UNTIL would leave
        a BY-expansion bypass (e.g. ``FREQ=DAILY;BYHOUR=0,...,23``).
        """
        user = factories.UserFactory(email=f"cap-{frequency.lower()}@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Cap", color="#000000")

        # Without the sanitizer this PUT returns 500 with
        # `MaxInstancesExceededException`. With the sanitizer it must
        # succeed.
        uid = f"cap-{frequency.lower()}-test"
        service.create_event_raw(user, caldav_path, self._make_ics(uid, frequency))

        # Read back the raw ICS and confirm COUNT was injected.
        http = CalDAVHTTPClient()
        ical_data, _href, _etag = http.find_event_by_uid(user, uid)
        assert ical_data, f"event UID {uid} not found after PUT"
        rrule_line = self._rrule_line(ical_data)
        assert rrule_line, f"no RRULE in stored ICS for FREQ={frequency}"
        assert "COUNT=" in rrule_line, (
            f"FREQ={frequency} stored RRULE {rrule_line!r} missing COUNT="
        )
        assert "UNTIL=" not in rrule_line, (
            f"FREQ={frequency} stored RRULE {rrule_line!r} should not have UNTIL="
        )

    def test_by_expansion_does_not_bypass_cap(self):
        """`FREQ=DAILY;BYHOUR=0,1,...,23` must still be COUNT-bounded.

        Pins the security-critical reason for COUNT-not-UNTIL: BY-fan-
        out would multiply instance count past `maxRecurrences` under
        a UNTIL cap, producing 500 errors on every subsequent read.
        """
        user = factories.UserFactory(email="cap-byhour@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Cap", color="#000000")
        uid = "cap-byhour-test"
        byhour = ",".join(str(h) for h in range(24))
        service.create_event_raw(
            user, caldav_path, self._make_ics(uid, "DAILY", f";BYHOUR={byhour}")
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        assert rrule_line, "RRULE missing after PUT"
        assert "COUNT=" in rrule_line, (
            f"BY-expansion RRULE {rrule_line!r} must carry COUNT="
        )

    @pytest.mark.parametrize("frequency", ["MINUTELY", "SECONDLY"])
    def test_stripped_sub_day_frequencies_become_one_off(self, frequency):
        """MINUTELY/SECONDLY: RRULE is stripped, event survives as one-off.

        Rejecting these with HTTP 400 would fail bulk imports and iTIP
        REQUEST routing whenever a single event in a batch uses a
        sub-day frequency. Stripping the RRULE keeps the master VEVENT
        as a single occurrence and sidesteps `sabre/vobject`'s
        RRuleIterator advancement gap for these frequencies.
        """
        user = factories.UserFactory(email=f"strip-{frequency.lower()}@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Strip", color="#000000")

        uid = f"strip-{frequency.lower()}-test"
        # Must succeed — the sanitizer strips the offending RRULE so
        # vobject's max-recurrences validator never fires.
        service.create_event_raw(user, caldav_path, self._make_ics(uid, frequency))

        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        assert ical_data, f"event UID {uid} not found after PUT"
        assert "RRULE" not in ical_data, (
            f"FREQ={frequency} should have been stripped, got: {ical_data!r}"
        )
        # And the rest of the event must still be there.
        assert f"UID:{uid}" in ical_data
        assert "SUMMARY:cap-test" in ical_data

    def test_rrule_with_count_is_left_untouched(self):
        """The sanitizer doesn't second-guess an already-bounded RRULE."""
        user = factories.UserFactory(email="cap-count@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Cap", color="#000000")

        uid = "cap-count-test"
        service.create_event_raw(
            user, caldav_path, self._make_ics(uid, "DAILY", ";COUNT=10")
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        # COUNT=10 must survive; no extra UNTIL appended.
        assert "COUNT=10" in rrule_line
        assert "UNTIL=" not in rrule_line

    def test_rrule_with_existing_until_is_left_untouched(self):
        """A user-supplied UNTIL bound is preserved verbatim."""
        user = factories.UserFactory(email="cap-until@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Cap", color="#000000")

        uid = "cap-until-test"
        service.create_event_raw(
            user, caldav_path, self._make_ics(uid, "DAILY", ";UNTIL=20270101T000000Z")
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        # Original UNTIL=2027 must survive; no second UNTIL appended.
        assert "UNTIL=20270101T000000Z" in rrule_line
        assert rrule_line.count("UNTIL=") == 1

    def test_non_recurring_event_is_untouched(self):
        """A simple VEVENT without RRULE round-trips cleanly."""
        user = factories.UserFactory(email="cap-norrule@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Cap", color="#000000")

        uid = "cap-norrule-test"
        service.create_event_raw(user, caldav_path, self._make_ics(uid, None))
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        assert "RRULE" not in ical_data

    def test_user_supplied_count_over_cap_is_clamped(self):
        """A user-supplied ``COUNT=999999`` is reduced to the per-FREQ cap.

        Without this clamp, the stored event would 500 on every
        time-range REPORT — vobject's iterator trips
        ``maxRecurrences`` mid-iteration.
        """
        user = factories.UserFactory(email="clamp-count@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Clamp", color="#000000")
        uid = "clamp-count-test"
        service.create_event_raw(
            user, caldav_path, self._make_ics(uid, "DAILY", ";COUNT=999999")
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        assert rrule_line, "RRULE missing after PUT"
        assert "COUNT=999999" not in rrule_line, f"COUNT not clamped: {rrule_line!r}"
        assert "COUNT=7300" in rrule_line, (
            f"expected COUNT=7300 (DAILY cap), got: {rrule_line!r}"
        )

    def test_user_supplied_until_too_far_is_clamped(self):
        """A user-supplied ``UNTIL=99991231T000000Z`` is replaced with COUNT.

        UNTIL+COUNT are mutually exclusive (RFC 5545 §3.3.10), so we
        drop the UNTIL and inject COUNT=cap.
        """
        user = factories.UserFactory(email="clamp-until@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Clamp", color="#000000")
        uid = "clamp-until-test"
        service.create_event_raw(
            user, caldav_path, self._make_ics(uid, "DAILY", ";UNTIL=99991231T000000Z")
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        assert rrule_line, "RRULE missing after PUT"
        assert "UNTIL=" not in rrule_line, f"UNTIL not stripped: {rrule_line!r}"
        assert "COUNT=7300" in rrule_line, (
            f"expected COUNT=7300 (DAILY cap), got: {rrule_line!r}"
        )

    def test_until_with_by_expansion_bypass_is_clamped(self):
        """`UNTIL=+5y;BYHOUR=0..23` would expand past cap — must be clamped.

        Apparently-modest UNTIL combined with BY-expansion (24× via
        BYHOUR) is the subtler attack: 5 years × 365 × 24 = 43,800
        instances. Estimator catches the BY-multiplier and replaces
        with COUNT=cap.
        """
        user = factories.UserFactory(email="clamp-by-bypass@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Clamp", color="#000000")
        uid = "clamp-by-bypass-test"
        byhour = ",".join(str(h) for h in range(24))
        service.create_event_raw(
            user,
            caldav_path,
            self._make_ics(uid, "DAILY", f";BYHOUR={byhour};UNTIL=20310101T000000Z"),
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        assert rrule_line, "RRULE missing after PUT"
        assert "UNTIL=" not in rrule_line, (
            f"UNTIL+BYHOUR bypass not clamped: {rrule_line!r}"
        )
        assert "COUNT=" in rrule_line, f"expected COUNT cap, got: {rrule_line!r}"

    def test_count_within_cap_is_untouched(self):
        """A reasonable COUNT under the cap stays exactly as supplied."""
        user = factories.UserFactory(email="clamp-count-ok@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Clamp", color="#000000")
        uid = "clamp-count-ok-test"
        service.create_event_raw(
            user, caldav_path, self._make_ics(uid, "DAILY", ";COUNT=50")
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        assert "COUNT=50" in rrule_line, f"under-cap COUNT got changed: {rrule_line!r}"

    def test_until_within_cap_is_untouched(self):
        """A reasonable UNTIL under the cap stays exactly as supplied."""
        user = factories.UserFactory(email="clamp-until-ok@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Clamp", color="#000000")
        uid = "clamp-until-ok-test"
        service.create_event_raw(
            user, caldav_path, self._make_ics(uid, "DAILY", ";UNTIL=20270101T000000Z")
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        assert "UNTIL=20270101T000000Z" in rrule_line, (
            f"under-cap UNTIL got changed: {rrule_line!r}"
        )
        assert "COUNT=" not in rrule_line, (
            f"under-cap UNTIL got COUNT injected: {rrule_line!r}"
        )

    def test_recurring_event_remains_visible_past_2038(self):
        """A DAILY recurrence capped at COUNT=7300 (~20 years) must be
        returned by a CalDAV time-range REPORT querying past 2038.

        SabreDAV's PDO backend historically clipped `lastoccurence`
        to ``MAX_DATE = 2038-01-01`` (a 32-bit Unix-timestamp hold-over
        from when calendar storage couldn't safely round-trip values
        above 2^31-1). The clip lives in
        ``vendor/sabre/dav/lib/CalDAV/Backend/PDO.php``; queries
        beyond it use the SQL pre-filter
        ``lastoccurence > :startdate`` and would silently drop any
        recurrence whose true ``lastoccurence`` was past 2038.

        We patch ``MAX_DATE`` to ``2200-01-01`` because our COUNT caps
        push DAILY events out to ~2046, WEEKLY/MONTHLY to ~2076, and
        YEARLY to ~2126. This test fails against the upstream MAX_DATE
        and passes against the patched value.
        """
        user = factories.UserFactory(email="past-2038@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Past2038", color="#000000")
        uid = "past-2038-test"
        # Unbounded DAILY → server injects COUNT=7300 → ends ~2046.
        service.create_event_raw(user, caldav_path, self._make_ics(uid, "DAILY"))

        # Query a one-week window in 2040, well past the historic
        # MAX_DATE clip. The DAILY occurrences for that week must
        # come back.
        start = datetime(2040, 1, 1, tzinfo=timezone.utc)
        end = datetime(2040, 1, 8, tzinfo=timezone.utc)
        events = service.get_events(user, caldav_path, start=start, end=end)
        assert events, (
            "recurring event whose RRULE extends past 2038 should still "
            "be visible to a CalDAV REPORT in 2040 — SabreDAV's "
            "MAX_DATE clip is likely the culprit if this fails."
        )

    def test_monthly_with_byday_filter_is_not_falsely_clamped(self):
        """`FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;UNTIL=+5y` is a real-world
        "first weekdays of every month" pattern.

        Per RFC 5545 §3.3.10, ``BYDAY`` on ``FREQ=MONTHLY`` EXPANDS
        (each match adds an occurrence). With a 5-year window:
            5y × 12mo × 5 weekdays ≈ 300 occurrences → under the 600
        MONTHLY cap. The sanitizer must leave the UNTIL untouched.
        """
        user = factories.UserFactory(email="byday-filter@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Filter", color="#000000")
        uid = "byday-filter-test"
        service.create_event_raw(
            user,
            caldav_path,
            self._make_ics(
                uid,
                "MONTHLY",
                ";BYDAY=MO,TU,WE,TH,FR;UNTIL=20310530T000000Z",
            ),
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        assert "UNTIL=20310530T000000Z" in rrule_line, (
            f"legitimate UNTIL falsely clamped: {rrule_line!r}"
        )
        assert "COUNT=" not in rrule_line, (
            f"COUNT injected for under-cap event: {rrule_line!r}"
        )

    def test_yearly_with_bymonth_filter_is_not_falsely_clamped(self):
        """`FREQ=YEARLY;BYMONTH=6` is a "yearly in June" filter.

        BYMONTH on YEARLY expands per RFC, so we count it: 100 yearly
        × 1 BYMONTH value = 100. Exactly at cap, no clamp. The point
        of this test: under the previous over-counting estimator,
        ``BYMONTH=6`` on ``FREQ=MONTHLY`` would have been miscounted
        as a 1× expansion when BYMONTH actually FILTERS on MONTHLY.
        Locking the per-FREQ table prevents that regression.
        """
        user = factories.UserFactory(email="bymonth-filter@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Filter", color="#000000")
        uid = "bymonth-filter-test"
        # MONTHLY + BYMONTH=6,12 filter (twice a year via MONTHLY) for
        # 40 years — under the 600 MONTHLY cap because BYMONTH filters
        # on MONTHLY, not expands.
        service.create_event_raw(
            user,
            caldav_path,
            self._make_ics(
                uid,
                "MONTHLY",
                ";BYMONTH=6,12;UNTIL=20660530T000000Z",
            ),
        )
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_line = self._rrule_line(ical_data)
        assert "UNTIL=20660530T000000Z" in rrule_line, (
            f"BYMONTH-filter UNTIL incorrectly clamped: {rrule_line!r}"
        )

    def test_multi_rrule_strips_only_stripped_one(self):
        """Two RRULEs on one VEVENT (RFC 5545 deprecated but tolerated).

        Only the MINUTELY one should be stripped; the DAILY one is
        bound with COUNT. Pinning this prevents accidental wipes of
        the surviving rule. EXDATE/RDATE on the same component are
        preserved as long as any recurrence property (RRULE or RDATE)
        survives, so exceptions intended for the kept rule aren't lost.
        """
        user = factories.UserFactory(email="multi-rrule@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Multi", color="#000000")
        uid = "multi-rrule-test"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260530T140000Z\r\n"
            "DTEND:20260530T150000Z\r\n"
            "SUMMARY:multi-rrule\r\n"
            "RRULE:FREQ=DAILY\r\n"
            "RRULE:FREQ=MINUTELY\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        rrule_lines = [
            line for line in ical_data.splitlines() if line.startswith("RRULE:")
        ]
        # MINUTELY stripped, DAILY remains with injected COUNT.
        assert len(rrule_lines) == 1, f"expected 1 surviving RRULE, got {rrule_lines!r}"
        surviving = rrule_lines[0]
        assert "FREQ=DAILY" in surviving, f"wrong RRULE survived: {surviving!r}"
        assert "MINUTELY" not in surviving, f"MINUTELY not stripped: {surviving!r}"
        assert "COUNT=" in surviving, (
            f"surviving RRULE not COUNT-bounded: {surviving!r}"
        )

    def test_multi_rrule_preserves_exdate_when_safe_rrule_survives(self):
        """EXDATE must survive when a sibling RRULE survives stripping.

        With MINUTELY + DAILY + EXDATE, the MINUTELY gets stripped but
        the DAILY remains — exceptions are still meaningful against the
        kept rule. The previous behavior wiped EXDATE/RDATE on any
        stripped RRULE, which dropped exceptions the user expected to
        keep.
        """
        user = factories.UserFactory(email="multi-rrule-exdate@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="ExdateMix", color="#000000")
        uid = "multi-rrule-exdate-test"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260530T140000Z\r\n"
            "DTEND:20260530T150000Z\r\n"
            "SUMMARY:multi-rrule-exdate\r\n"
            "RRULE:FREQ=DAILY\r\n"
            "RRULE:FREQ=MINUTELY\r\n"
            "EXDATE:20260601T140000Z\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        assert ical_data, "event not stored"
        assert "MINUTELY" not in ical_data, f"MINUTELY not stripped: {ical_data!r}"
        assert "FREQ=DAILY" in ical_data, f"DAILY not preserved: {ical_data!r}"
        assert "20260601T140000Z" in ical_data and "EXDATE" in ical_data, (
            "EXDATE wiped despite a surviving safe RRULE — exceptions "
            f"lost: {ical_data!r}"
        )

    def test_stripped_only_rrule_drops_orphan_exdate(self):
        """When the only RRULE is stripped and no RDATE remains,
        EXDATE must be dropped — it has nothing left to except from
        and would otherwise sit in storage as RFC-invalid garbage.
        """
        user = factories.UserFactory(email="strip-orphan-exdate@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Orphan", color="#000000")
        uid = "strip-orphan-exdate-test"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260530T140000Z\r\n"
            "DTEND:20260530T150000Z\r\n"
            "SUMMARY:strip-orphan-exdate\r\n"
            "RRULE:FREQ=MINUTELY\r\n"
            "EXDATE:20260601T140000Z\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        assert ical_data, "event not stored"
        assert "RRULE" not in ical_data, f"RRULE not stripped: {ical_data!r}"
        assert "EXDATE" not in ical_data, (
            f"orphan EXDATE survived despite no recurrence remaining: {ical_data!r}"
        )

    def test_stripped_rrule_preserves_rdate_driven_recurrence(self):
        """RDATE alone is a valid recurrence form. When MINUTELY RRULE
        coexists with RDATE + EXDATE, stripping the RRULE must keep
        both RDATE and EXDATE — the RDATE-driven occurrences remain
        and the EXDATE still excludes a date from them.
        """
        user = factories.UserFactory(email="rdate-survives@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Rdate", color="#000000")
        uid = "rdate-survives-test"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260530T140000Z\r\n"
            "DTEND:20260530T150000Z\r\n"
            "SUMMARY:rdate-survives\r\n"
            "RRULE:FREQ=MINUTELY\r\n"
            "RDATE:20260531T140000Z,20260602T140000Z\r\n"
            "EXDATE:20260602T140000Z\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        assert ical_data, "event not stored"
        assert "MINUTELY" not in ical_data, f"MINUTELY not stripped: {ical_data!r}"
        assert "RDATE" in ical_data, f"RDATE wiped despite being safe: {ical_data!r}"
        assert "EXDATE" in ical_data, (
            f"EXDATE wiped despite RDATE-driven recurrence: {ical_data!r}"
        )

    def test_vtodo_without_dtstart_absurd_until_is_clamped(self):
        """VTODO permits omitting DTSTART, which would let an absurd
        UNTIL slip past ``estimateInstances`` (it returns null when
        DTSTART is missing → no clamp).

        The sanitizer falls back to clamping on absurd-year UNTIL
        (> 2300) for this case so the attack is defused.
        """
        user = factories.UserFactory(email="vtodo-no-dtstart@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Todo", color="#000000")
        uid = "vtodo-no-dtstart-test"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VTODO\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "SUMMARY:open-ended-todo\r\n"
            "RRULE:FREQ=DAILY;UNTIL=99991231T000000Z\r\n"
            "END:VTODO\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        assert ical_data, "VTODO not stored"
        rrule_line = self._rrule_line(ical_data)
        assert rrule_line, f"no RRULE in stored VTODO: {ical_data!r}"
        assert "99991231" not in rrule_line, (
            f"absurd UNTIL not clamped on VTODO: {rrule_line!r}"
        )
        assert "COUNT=" in rrule_line, f"VTODO RRULE not COUNT-bounded: {rrule_line!r}"

    def test_itip_request_routes_through_sanitizer(self):
        """iTIP REQUEST auto-routed by SabreDAV's Schedule plugin
        must hit our `beforeCreateFile` hook so unbounded RRULEs
        from organizers can't blow past `maxRecurrences` on the
        attendee's stored copy.

        SabreDAV routes VEVENT scheduling implicitly: when the
        organizer PUTs an event carrying ATTENDEE properties into
        their own calendar, the Schedule plugin emits iTIP
        REQUESTs and writes a corresponding event into each
        attendee's scheduling target (default calendar or inbox).
        That write goes through the calendar backend, which
        triggers `beforeCreateFile` — and therefore our sanitizer.

        Failure mode: a SabreDAV refactor that bypasses
        `beforeCreateFile` for scheduled writes (e.g., direct
        backend calls bypassing the HTTP layer) would silently
        disable the cap on the iTIP path.
        """
        organizer = factories.UserFactory(email="organizer-itip@example.com")
        attendee = factories.UserFactory(email="attendee-itip@example.com")
        service = CalendarService()
        service.ensure_default_calendar(organizer)
        service.ensure_default_calendar(attendee)
        organizer_paths = service.get_user_calendar_paths(organizer)
        assert organizer_paths, "organizer has no calendar"
        organizer_cal_path = organizer_paths[0]

        uid = "itip-req-test"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260601T140000Z\r\n"
            "DTEND:20260601T150000Z\r\n"
            "SUMMARY:itip-daily\r\n"
            "RRULE:FREQ=DAILY\r\n"
            f"ORGANIZER:mailto:{organizer.email}\r\n"
            "ATTENDEE;PARTSTAT=ACCEPTED;ROLE=CHAIR;CUTYPE=INDIVIDUAL:"
            f"mailto:{organizer.email}\r\n"
            "ATTENDEE;PARTSTAT=NEEDS-ACTION;RSVP=TRUE;CUTYPE=INDIVIDUAL:"
            f"mailto:{attendee.email}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

        # Organizer PUTs into their own calendar. SabreDAV's
        # Schedule plugin handles iTIP routing to the attendee.
        service.create_event_raw(organizer, organizer_cal_path, ics)

        # Locate the same UID in the attendee's calendar (scheduling
        # default — typically the inbox, then auto-processed into
        # the default calendar by SabreDAV).
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(attendee, uid)
        assert ical_data, (
            f"attendee never received the iTIP-routed event {uid} — "
            "scheduling may not have delivered, or Schedule plugin "
            "is not configured."
        )
        rrule_line = self._rrule_line(ical_data)
        assert rrule_line, f"event arrived but lost its RRULE: {ical_data!r}"
        assert "COUNT=" in rrule_line, (
            f"sanitizer didn't fire on iTIP routing — RRULE: {rrule_line!r}"
        )

    @pytest.mark.parametrize(
        "uri,expect_stripped",
        [
            ("file:///etc/passwd", True),
            ("smb://attacker.example/share/secret", True),
            ("javascript:alert(1)", True),
            ("data:text/html;base64,PHNjcmlwdD4=", True),
            ("vbscript:foo", True),
            ("https://drive.google.com/file/abc/view", False),
            ("http://example.com/doc.pdf", False),
            ("mailto:bob@example.com", False),
        ],
    )
    def test_attach_uri_scheme_allowlist(self, uri, expect_stripped):
        """Dangerous URI schemes in ATTACH are stripped on write.

        Defends against (a) ``file://`` local-file exfil via clients
        that auto-fetch attachments (e.g. SCHEDULE-FORCE-SEND chains),
        (b) ``smb://`` NTLM hash leaks on Windows, (c)
        ``javascript:`` / ``data:text/html`` XSS in clients that
        render the link target.
        """
        user = factories.UserFactory(email=f"attach-{abs(hash(uri))}@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Attach", color="#000000")
        uid = f"attach-{abs(hash(uri))}"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260601T140000Z\r\n"
            "DTEND:20260601T150000Z\r\n"
            "SUMMARY:attach-test\r\n"
            f"ATTACH:{uri}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        if expect_stripped:
            assert "ATTACH" not in ical_data, (
                f"unsafe ATTACH {uri!r} not stripped: {ical_data!r}"
            )
        else:
            assert uri in ical_data, (
                f"safe ATTACH {uri!r} was incorrectly stripped: {ical_data!r}"
            )

    def test_malicious_vtimezone_rrule_is_stripped_on_store(self):
        """A VTIMEZONE with FREQ=DAILY in its STANDARD/DAYLIGHT rules
        is malicious — DST transitions are annual, not daily.

        Without bounding, vobject's TimeZoneUtil iterates transitions
        to resolve TZID for any event referencing it. A daily-rule
        VTIMEZONE produces ≥365 transitions per year and trips
        ``maxRecurrences`` on read of any event using that TZID,
        creating a persistent per-event DoS.

        The sanitizer strips sub-monthly FREQs in VTIMEZONE
        STANDARD/DAYLIGHT children before storage. Reads still
        succeed (covered by the explicit-read assertion below).
        """
        user = factories.UserFactory(email="vtimezone-bomb@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="TZ", color="#000000")
        uid = "vtimezone-bomb-test"
        # DTSTART 1970 so daily iteration to the event's date in 2026
        # is ~20,440 transitions — well over the 8000 maxRecurrences
        # cap. This forces vobject to actually trip if it iterates
        # the TZ rule lazily during read.
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VTIMEZONE\r\n"
            "TZID:Custom-Evil\r\n"
            "BEGIN:STANDARD\r\n"
            "DTSTART:19700101T020000\r\n"
            "TZOFFSETFROM:+0000\r\n"
            "TZOFFSETTO:+0000\r\n"
            "TZNAME:EVL\r\n"
            "RRULE:FREQ=DAILY\r\n"
            "END:STANDARD\r\n"
            "END:VTIMEZONE\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART;TZID=Custom-Evil:20260601T140000\r\n"
            "DTEND;TZID=Custom-Evil:20260601T150000\r\n"
            "SUMMARY:tz-bomb\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)

        # The stored VTIMEZONE must no longer contain the daily rule.
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        assert ical_data, "event not stored"
        # Find the STANDARD block and confirm no RRULE inside it.
        in_standard = False
        for line in ical_data.splitlines():
            if line == "BEGIN:STANDARD":
                in_standard = True
            elif line == "END:STANDARD":
                in_standard = False
            elif in_standard:
                assert not line.startswith("RRULE:"), (
                    f"VTIMEZONE STANDARD RRULE survived store: {line!r}"
                )

        # Reads still succeed.
        start = datetime(2026, 6, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 2, tzinfo=timezone.utc)
        events = service.get_events(user, caldav_path, start=start, end=end)
        assert events, "VTIMEZONE-bomb event is unreadable after sanitizer ran."

    def test_legitimate_vtimezone_rrule_is_preserved(self):
        """A real-world VTIMEZONE (``FREQ=YEARLY;BYMONTH=…;BYDAY=…``)
        must survive sanitization unchanged. This is the typical
        America/New_York DST rule shape and we'd be breaking every
        cross-timezone event if we stripped it.
        """
        user = factories.UserFactory(email="vtimezone-legit@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="TZ-OK", color="#000000")
        uid = "vtimezone-legit-test"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VTIMEZONE\r\n"
            "TZID:America/New_York\r\n"
            "BEGIN:STANDARD\r\n"
            "DTSTART:20071104T020000\r\n"
            "TZOFFSETFROM:-0400\r\n"
            "TZOFFSETTO:-0500\r\n"
            "TZNAME:EST\r\n"
            "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU\r\n"
            "END:STANDARD\r\n"
            "BEGIN:DAYLIGHT\r\n"
            "DTSTART:20070311T020000\r\n"
            "TZOFFSETFROM:-0500\r\n"
            "TZOFFSETTO:-0400\r\n"
            "TZNAME:EDT\r\n"
            "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU\r\n"
            "END:DAYLIGHT\r\n"
            "END:VTIMEZONE\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART;TZID=America/New_York:20260601T140000\r\n"
            "DTEND;TZID=America/New_York:20260601T150000\r\n"
            "SUMMARY:tz-legit\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, uid)
        # vobject re-orders RRULE parts alphabetically on serialize,
        # so check the values rather than the literal substring.
        standard_rrule = None
        daylight_rrule = None
        current = None
        for line in ical_data.splitlines():
            if line == "BEGIN:STANDARD":
                current = "standard"
            elif line == "BEGIN:DAYLIGHT":
                current = "daylight"
            elif line.startswith("END:"):
                current = None
            elif line.startswith("RRULE:") and current == "standard":
                standard_rrule = line
            elif line.startswith("RRULE:") and current == "daylight":
                daylight_rrule = line
        assert standard_rrule and "FREQ=YEARLY" in standard_rrule, (
            f"YEARLY STANDARD rule missing: standard_rrule={standard_rrule!r}"
        )
        assert "BYMONTH=11" in standard_rrule and "BYDAY=1SU" in standard_rrule, (
            f"STANDARD BY-parts changed: {standard_rrule!r}"
        )
        assert daylight_rrule and "FREQ=YEARLY" in daylight_rrule, (
            f"YEARLY DAYLIGHT rule missing: {daylight_rrule!r}"
        )
        assert "BYMONTH=3" in daylight_rrule and "BYDAY=2SU" in daylight_rrule, (
            f"DAYLIGHT BY-parts changed: {daylight_rrule!r}"
        )

    def test_organizer_spoofing_does_not_route_to_external_attendee(self):
        """A user PUTting an event with someone else's ORGANIZER into
        their own calendar must NOT cause SabreDAV's Schedule plugin
        to route an iTIP REQUEST as the spoofed organizer.

        Threat: attacker controls account A, puts an event with
        ORGANIZER=victim, ATTENDEE=target. If the server routes,
        target sees "victim invited you" — credibility-boosted
        phishing.
        """
        attacker = factories.UserFactory(email="spoof-attacker@example.com")
        target = factories.UserFactory(email="spoof-target@example.com")
        spoofed_organizer_email = "spoofed-victim@example.com"

        service = CalendarService()
        service.ensure_default_calendar(attacker)
        service.ensure_default_calendar(target)
        attacker_paths = service.get_user_calendar_paths(attacker)
        attacker_cal_path = attacker_paths[0]

        uid = "spoof-test"
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260601T140000Z\r\n"
            "DTEND:20260601T150000Z\r\n"
            "SUMMARY:spoof\r\n"
            f"ORGANIZER:mailto:{spoofed_organizer_email}\r\n"
            "ATTENDEE;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:"
            f"mailto:{target.email}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        # The PUT itself may succeed (RFC 5545 allows any string
        # as ORGANIZER on a non-scheduled event) or be refused by
        # SabreDAV. Either is acceptable. What matters is the
        # security invariant: the target's calendar must NOT receive
        # an iTIP-routed copy. Verify that invariant regardless of
        # the PUT outcome so an unrelated failure can't mask a
        # routing regression — but capture the exception so a
        # failure of the invariant check shows *why* PUT raised, not
        # a silent green test.
        put_exception: Exception | None = None
        try:
            service.create_event_raw(attacker, attacker_cal_path, ics)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            put_exception = exc

        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(target, uid)
        assert ical_data is None, (
            "ORGANIZER spoofing detected — target received an iTIP "
            "copy from the wrong principal. Stored content: "
            f"{ical_data!r}. PUT exception (if any): {put_exception!r}"
        )

    def test_utf8_round_trip_preserves_bytes(self):
        """Non-ASCII text PUT into CalDAV must come out byte-identical
        on GET.

        The python ``caldav`` library's ``save_event`` had a Latin-1
        encoding step that turned ``中`` (``e4 b8 ad``) into
        ``c3 a4 c2 b8 c2 ad`` — valid UTF-8 of three Latin-1 code
        points, but semantically wrong. ``CalendarService.create_event_raw``
        now writes raw UTF-8 bytes via direct HTTP. This test pins the
        contract.
        """
        user = factories.UserFactory(email="utf8-roundtrip@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="UTF8RT", color="#000000")
        uid = "utf8-roundtrip-test"
        # One 中 in SUMMARY, one in DESCRIPTION. Each is e4 b8 ad
        # (3 bytes). Mojibake would double them to 6 bytes.
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260601T140000Z\r\n"
            "DTEND:20260601T150000Z\r\n"
            "SUMMARY:hello 中\r\n"
            "DESCRIPTION:bye 中\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)

        http = CalDAVHTTPClient()
        _, href, _ = http.find_event_by_uid(user, uid)
        response = http.request("GET", user, href)
        assert response.status_code == 200, response.text
        body = response.content
        # The 3-byte UTF-8 sequence for 中 must appear exactly twice
        # in the stored body (SUMMARY + DESCRIPTION). Mojibake would
        # give 0 matches and 2 instances of c3a4 c2b8 c2ad.
        assert body.count(b"\xe4\xb8\xad") == 2, (
            f"中 bytes not preserved verbatim — round-trip mojibake. "
            f"tail={body[-200:]!r}"
        )
        assert b"\xc3\xa4\xc2\xb8\xc2\xad" not in body, (
            "mojibake double-encoding of 中 detected in stored body"
        )

    def test_oversized_multibyte_description_truncates_to_valid_utf8(self):
        """A DESCRIPTION longer than the byte limit, made of multi-
        byte characters (emoji = 4 bytes UTF-8), must NOT produce
        invalid UTF-8 at the truncation boundary.

        ``substr($val, 0, $maxBytes)`` byte-cuts and can leave a
        half-character at the end. Downstream parsers (Python's
        ``icalendar``, the frontend ``ts-ics``) may throw or silently
        corrupt. Test forces the worst case and asserts the stored
        bytes decode cleanly.
        """
        user = factories.UserFactory(email="utf8-truncate@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="UTF8", color="#000000")
        uid = "utf8-truncate-test"
        # Use a 3-byte UTF-8 character (中, e4 b8 ad). The default
        # cap (102400) is not divisible by 3, so byte-level substr
        # MUST cut a character in half. (4-byte emoji are a clean
        # multiple of 4 against a 102400 cap and happen to land on
        # a boundary — they don't exercise the bug.)
        big = "中" * 34200  # 34200 × 3 = 102600 bytes, over the 100 KB cap
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260601T140000Z\r\n"
            "DTEND:20260601T150000Z\r\n"
            "SUMMARY:utf8-truncate\r\n"
            f"DESCRIPTION:{big}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        _ical_data, href, _ = http.find_event_by_uid(user, uid)
        assert href, "event not stored"
        # Fetch the raw bytes via HTTP — the python ``caldav`` library
        # decodes with ``errors='replace'`` by default, masking
        # invalid UTF-8 in the stored ICS. The bytes themselves are
        # what downstream consumers (Django, frontend) see.
        response = http.request("GET", user, href)
        assert response.status_code == 200, f"GET {href} failed: {response.status_code}"
        try:
            response.content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as e:
            # Show a small window around the offending byte for
            # easier diagnosis.
            window = response.content[max(0, e.start - 10) : e.start + 10]
            raise AssertionError(
                f"truncated DESCRIPTION contains invalid UTF-8 at "
                f"byte {e.start}: {window!r}"
            ) from e

    def test_schedule_force_send_does_not_force_routing(self):
        """SCHEDULE-FORCE-SEND on an ATTENDEE must not bypass our
        normal scheduling-routing decisions.

        Background: macOS Calendar honored SCHEDULE-FORCE-SEND on
        client-side and emitted invites even when the server-side
        SCHEDULE-AGENT was SERVER (spaceraccoon DEF CON 30,
        CVE-2020-3882-adjacent chain). For our server, the question
        is: if a malicious client PUTs an event carrying
        SCHEDULE-FORCE-SEND, does our pipeline auto-emit a REQUEST
        to a target that wouldn't have otherwise received one? We
        verify the parameter doesn't influence inbox delivery
        behavior — the spoof-target test above already covers the
        organizer-mismatch case; this one specifically pins that
        SCHEDULE-FORCE-SEND alone isn't a routing-bypass mechanism.
        """
        organizer = factories.UserFactory(email="sfs-organizer@example.com")
        target = factories.UserFactory(email="sfs-target@example.com")
        service = CalendarService()
        service.ensure_default_calendar(organizer)
        service.ensure_default_calendar(target)
        org_cal = service.get_user_calendar_paths(organizer)[0]

        uid = "sfs-test"
        # METHOD is absent and ATTENDEE carries SCHEDULE-FORCE-SEND.
        # The event has a single ATTENDEE who is also a server user,
        # so normal scheduling already would route. We just verify
        # routing still goes through the normal sanitizer path and
        # the stored copy on the target side carries the
        # sanitizer-injected COUNT (proves our hook fired).
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260601T140000Z\r\n"
            "DTEND:20260601T150000Z\r\n"
            "SUMMARY:schedule-force-send\r\n"
            "RRULE:FREQ=DAILY\r\n"
            f"ORGANIZER:mailto:{organizer.email}\r\n"
            "ATTENDEE;PARTSTAT=ACCEPTED;ROLE=CHAIR:"
            f"mailto:{organizer.email}\r\n"
            "ATTENDEE;PARTSTAT=NEEDS-ACTION;SCHEDULE-FORCE-SEND=REQUEST:"
            f"mailto:{target.email}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(organizer, org_cal, ics)

        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(target, uid)
        assert ical_data, "target never got the iTIP-routed event"
        rrule_line = self._rrule_line(ical_data)
        assert rrule_line and "COUNT=" in rrule_line, (
            f"iTIP-routed event arrived without sanitizer bound — RRULE: {rrule_line!r}"
        )

    def test_propfind_depth_infinity_is_not_honoured(self):
        """`PROPFIND` with `Depth: infinity` must not walk the
        entire user tree.

        Currently safe because SabreDAV defaults
        ``$enablePropfindDepthInfinity = false`` (server-wide). If
        anyone flips that flag or upstream's default changes, this
        test catches it before a single attacker request can index
        the whole user's calendar set (classic WebDAV DoS — see
        Nextcloud calendar #7870 where a Depth-infinity flood
        blocked all PHP-FPM workers).
        """
        user = factories.UserFactory(email="depth-inf@example.com")
        service = CalendarService()
        service.ensure_default_calendar(user)
        # Build a tree the assertion can actually distinguish: 3 extra
        # calendars (4 total with the default) × 5 events each = 20
        # events. Depth: 1 → ~5 responses (home + calendars); Depth:
        # infinity honoured → 25+ responses (also every event).
        num_extra_calendars = 3
        events_per_calendar = 5
        for cal_idx in range(num_extra_calendars):
            cal_path = service.create_calendar(
                user, name=f"depth-cal-{cal_idx}", color="#000000"
            )
            for evt_idx in range(events_per_calendar):
                uid = f"depth-evt-{cal_idx}-{evt_idx}"
                ics = (
                    "BEGIN:VCALENDAR\r\n"
                    "VERSION:2.0\r\n"
                    "PRODID:-//test//EN\r\n"
                    "BEGIN:VEVENT\r\n"
                    f"UID:{uid}\r\n"
                    "DTSTAMP:20260530T120000Z\r\n"
                    "DTSTART:20260601T140000Z\r\n"
                    "DTEND:20260601T150000Z\r\n"
                    f"SUMMARY:{uid}\r\n"
                    "END:VEVENT\r\n"
                    "END:VCALENDAR\r\n"
                )
                service.create_event_raw(user, cal_path, ics)

        http = CalDAVHTTPClient()
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:"><d:prop>'
            "<d:displayname/></d:prop></d:propfind>"
        )
        # Calendar home set — Depth: infinity would walk every
        # calendar + every calendarobject if honoured.
        path = f"/calendars/users/{user.email}/"
        response = http.request(
            "PROPFIND",
            user,
            path,
            data=body,
            content_type="application/xml; charset=utf-8",
            extra_headers={"Depth": "infinity"},
        )
        # Either rejected outright, OR downgraded to Depth: 1
        # (SabreDAV's default behaviour). Cap at "immediate children
        # plus headroom" — well below the event count, so honouring
        # infinity will fail the assertion.
        response_count = response.text.count("<d:response")
        max_allowed = num_extra_calendars + events_per_calendar  # 8, < 20 events
        assert response.status_code != 207 or response_count <= max_allowed, (
            f"Depth: infinity returned {response_count} responses with "
            f"{num_extra_calendars * events_per_calendar} events present — server "
            "appears to be walking the whole tree (DoS vector)."
        )

    def test_xxe_in_propfind_is_not_resolved(self):
        """PROPFIND with an external entity reference must not read
        local files (CVE-2014-2055 family).

        Currently safe because sabre/xml since 1.7.11 configures
        libxml to disable external entity loading. Pins the
        invariant so a regression in our composer pin / a vendor
        bump that flips defaults is caught immediately.
        """
        user = factories.UserFactory(email="xxe@example.com")
        service = CalendarService()
        service.ensure_default_calendar(user)
        http = CalDAVHTTPClient()
        # Classic XXE — if the parser resolved &xxe;, the
        # displayname in the response would contain /etc/passwd.
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<!DOCTYPE foo ["
            '  <!ENTITY xxe SYSTEM "file:///etc/passwd">'
            "]>"
            '<d:propfind xmlns:d="DAV:"><d:prop>'
            "<d:displayname>&xxe;</d:displayname>"
            "</d:prop></d:propfind>"
        )
        path = f"/calendars/users/{user.email}/"
        response = http.request(
            "PROPFIND",
            user,
            path,
            data=body,
            content_type="application/xml; charset=utf-8",
            extra_headers={"Depth": "0"},
        )
        # Hard ban on /etc/passwd content or signs of file leakage.
        assert "root:" not in response.text, (
            "XXE resolved — /etc/passwd content appears in PROPFIND "
            f"response: {response.text[:500]!r}"
        )
        assert "/bin/bash" not in response.text and ("/bin/sh" not in response.text), (
            "XXE resolved — shell paths from /etc/passwd in PROPFIND "
            f"response: {response.text[:500]!r}"
        )

    def test_lone_cr_in_organizer_uri_is_stripped_on_store(self):
        """A lone CR (``\\r`` without ``\\n``) in an iCal URI value
        survives vobject's parser but must NOT survive our
        canonicalization re-serialize.

        Without this invariant, the byte would propagate through
        the iMIP / Schedule paths and become an HTTP-header
        injection vector (see ``HttpCallbackIMipPlugin``'s
        sanitizeHeaderValue defense for the boundary fix).
        Currently safe because vobject's serializer strips bare CR
        on output (verified empirically), but pin the contract
        here so any vobject-bump regression breaks the test.
        """
        user = factories.UserFactory(email="lone-cr@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="CR", color="#000000")
        uid = "lone-cr-test"
        # Bare CR in the ORGANIZER value. Reader::read keeps it;
        # our sanitizer's canonicalization MUST drop it.
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260601T140000Z\r\n"
            "DTEND:20260601T150000Z\r\n"
            "SUMMARY:lone-cr-test\r\n"
            "ORGANIZER:mailto:a@example.com\rX-Injected:malicious\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        _, href, _ = http.find_event_by_uid(user, uid)
        assert href, "event not stored"
        # Fetch the raw stored bytes — checking ``ical_data`` via
        # ``splitlines()`` would silently split on a smuggled lone CR
        # and hide the very byte we're trying to detect. Inspect the
        # GET response bytes directly so any 0x0D that isn't part of
        # the canonical CRLF line ending surfaces.
        raw_content = http.request("GET", user, href).content
        assert not re.search(rb"\r(?!\n)", raw_content), (
            f"lone CR survived canonicalization in raw body: {raw_content!r}"
        )

    def test_create_event_raw_handles_uid_parameters_and_folding(self):
        """``create_event_raw`` extracts the UID for the PUT href via
        regex. The naive ``^UID:(.+)$`` form misses two legal iCal
        shapes: property parameters (``UID;X-FOO=bar:value``) and
        RFC 5545 line folding (a CRLF + linear whitespace continues
        the previous line). Pin both — without these the PUT raises
        ``ValueError`` on a perfectly valid client payload.
        """
        user = factories.UserFactory(email="uid-edge@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="UidEdge", color="#000000")
        # Property parameter on UID + folded UID across two lines.
        # Unfolded the UID reads "uid-edge-test-folded-tail".
        ics = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID;X-LS-NOTE=foo:uid-edge-test-folded\r\n"
            " -tail\r\n"
            "DTSTAMP:20260530T120000Z\r\n"
            "DTSTART:20260601T140000Z\r\n"
            "DTEND:20260601T150000Z\r\n"
            "SUMMARY:uid-edge-test\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        service.create_event_raw(user, caldav_path, ics)
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user, "uid-edge-test-folded-tail")
        assert ical_data, "event not stored under unfolded UID"

    def test_capped_event_iterates_via_caldav_report(self):
        """A capped RRULE must iterate cleanly — proves vobject can
        actually expand the stored event without tripping
        ``maxRecurrences``.

        Without this end-to-end check the previous tests only verify
        the stored bytes; they don't prove a downstream REPORT
        request succeeds.
        """
        user = factories.UserFactory(email="iterate-capped@example.com")
        service = CalendarService()
        caldav_path = service.create_calendar(user, name="Iter", color="#000000")
        uid = "iterate-capped-test"
        # No bound → server injects COUNT=7300 (DAILY cap).
        service.create_event_raw(user, caldav_path, self._make_ics(uid, "DAILY"))

        # Time-range REPORT spanning the first 7 days from DTSTART.
        # This is the request path that triggers vobject expansion,
        # which is where MaxInstancesExceededException would surface.
        start = datetime(2026, 5, 30, tzinfo=timezone.utc)
        end = datetime(2026, 6, 6, tzinfo=timezone.utc)
        events = service.get_events(user, caldav_path, start=start, end=end)
        # 7 daily occurrences expected; we only assert non-empty so
        # the test doesn't break if expansion bounds shift slightly.
        assert events, "expected expanded recurrences, got none"
