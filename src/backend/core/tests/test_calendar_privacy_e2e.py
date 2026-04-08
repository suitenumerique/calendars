"""E2E tests for CLASS enforcement and VALARM stripping on shared calendars.

Tests that CLASS:PRIVATE hides events entirely, CLASS:CONFIDENTIAL shows
only time blocks, and VALARM components are stripped for non-owners.
Requires: CalDAV server running.
"""

# pylint: disable=no-member,broad-exception-caught,unused-variable,too-many-lines

import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

import pytest
from rest_framework.test import APIClient

from core import factories
from core.entitlements.factory import get_entitlements_backend
from core.services.caldav_service import CalDAVHTTPClient, CalendarService
from core.services.import_service import ICSImportService

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.xdist_group("caldav"),
]


@pytest.fixture(autouse=True)
def _local_entitlements(settings):
    """Use local entitlements backend."""
    settings.ENTITLEMENTS_BACKEND = (
        "core.entitlements.backends.local.LocalEntitlementsBackend"
    )
    settings.ENTITLEMENTS_BACKEND_PARAMETERS = {}
    get_entitlements_backend.cache_clear()
    yield
    get_entitlements_backend.cache_clear()


def _create_user_with_calendar(org, email_prefix):
    """Create a user with a calendar."""
    user = factories.UserFactory(
        email=f"{email_prefix}@privacy-test.com", organization=org
    )
    client = APIClient()
    client.force_login(user)
    service = CalendarService()
    caldav_path = service.create_calendar(user, name=f"{email_prefix}'s Cal")
    return user, client, caldav_path


def _get_cal_id(caldav_path):
    parts = caldav_path.strip("/").split("/")
    return parts[-1] if len(parts) >= 4 else "default"


def _share_calendar(owner_client, owner, cal_id, sharee_email, privilege):
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
        "<CS:set>"
        f"<D:href>mailto:{sharee_email}</D:href>"
        f"<CS:{privilege}/>"
        "</CS:set>"
        "</CS:share>"
    )
    return owner_client.generic(
        "POST",
        f"/caldav/calendars/users/{owner.email}/{cal_id}/",
        data=body,
        content_type="application/xml",
    )


def _put_event_with_class(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    owner_client,
    owner,
    cal_id,
    uid,
    summary,
    classification,
    description="",
    location="",
    valarm=False,
):
    """PUT an event with a specific CLASS value and optional VALARM."""
    dtstart = datetime.now() + timedelta(days=1)
    dtend = dtstart + timedelta(hours=1)
    alarm_block = ""
    if valarm:
        alarm_block = (
            "BEGIN:VALARM\r\n"
            "ACTION:DISPLAY\r\n"
            "DESCRIPTION:Reminder\r\n"
            "TRIGGER:-PT15M\r\n"
            "END:VALARM\r\n"
        )
    desc_line = f"DESCRIPTION:{description}\r\n" if description else ""
    loc_line = f"LOCATION:{location}\r\n" if location else ""
    ical = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"SUMMARY:{summary}\r\n"
        f"CLASS:{classification}\r\n"
        f"{desc_line}"
        f"{loc_line}"
        f"{alarm_block}"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return owner_client.generic(
        "PUT",
        f"/caldav/calendars/users/{owner.email}/{cal_id}/{uid}.ics",
        data=ical,
        content_type="text/calendar",
    )


def _get_calendar_urls(user):
    return {
        str(c.url)
        for c in CalDAVHTTPClient().get_dav_client(user).principal().calendars()
    }


def _share_and_find(owner_client, owner, cal_id, sharee, privilege):
    urls_before = _get_calendar_urls(sharee)
    resp = _share_calendar(owner_client, owner, cal_id, sharee.email, privilege)
    assert resp.status_code in (200, 204)
    cals = CalDAVHTTPClient().get_dav_client(sharee).principal().calendars()
    new = [c for c in cals if str(c.url) not in urls_before]
    assert len(new) == 1, f"Expected 1 new calendar, got {len(new)}"
    return new[0]


class TestClassConfidentialEnforcement:
    """CLASS:CONFIDENTIAL events should show as 'Busy' on shared calendars."""

    def test_confidential_event_summary_hidden_from_sharee(self):
        """Sharee sees 'Busy' instead of the actual summary."""
        org = factories.OrganizationFactory(external_id="class-conf-summary")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-cc")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-cc")
        cal_id = _get_cal_id(cal_path)

        _put_event_with_class(
            owner_client,
            owner,
            cal_id,
            "conf-event",
            "Secret Board Meeting",
            "CONFIDENTIAL",
            description="Discussing layoffs",
            location="CEO Suite",
        )

        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        events = shared_cal.events()
        assert len(events) > 0, "Shared calendar should have events"
        found_target = False
        for ev in events:
            data = str(ev.data)
            if "conf-event" in data:
                found_target = True
                # Unfold long iCalendar lines for substring assertions.
                unfolded = (
                    data.replace("\r\n ", "")
                    .replace("\r\n\t", "")
                    .replace("\n ", "")
                    .replace("\n\t", "")
                )
                assert "Secret Board Meeting" not in unfolded, (
                    "SECURITY: CONFIDENTIAL event SUMMARY visible to sharee"
                )
                assert "Discussing layoffs" not in unfolded, (
                    "SECURITY: CONFIDENTIAL event DESCRIPTION visible to sharee"
                )
                assert "CEO Suite" not in unfolded, (
                    "SECURITY: CONFIDENTIAL event LOCATION visible to sharee"
                )
                # The CONFIDENTIAL replacement summary must be exactly
                # ``SUMMARY:Busy`` — checking just ``"Busy" in data`` would
                # match e.g. ``X-WR-CALNAME:Busybox`` or any future property
                # that contains the substring.
                assert "SUMMARY:Busy" in unfolded, (
                    "CONFIDENTIAL event SUMMARY should be replaced with 'Busy'. "
                    f"Got: {unfolded[:500]}"
                )
                # No DESCRIPTION or LOCATION should be present at all on
                # the rewritten event (the privacy plugin strips them).
                assert "DESCRIPTION:" not in unfolded, (
                    "CONFIDENTIAL event must have no DESCRIPTION property "
                    f"at all. Got: {unfolded[:500]}"
                )
                assert "LOCATION:" not in unfolded, (
                    "CONFIDENTIAL event must have no LOCATION property "
                    f"at all. Got: {unfolded[:500]}"
                )
                assert "DTSTART" in unfolded, "Time info should be preserved"
        assert found_target, "Target CONFIDENTIAL event not found in shared calendar"

    def test_confidential_event_visible_to_owner(self):
        """Owner should still see full details of their CONFIDENTIAL events."""
        org = factories.OrganizationFactory(external_id="class-conf-owner")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-co")
        cal_id = _get_cal_id(cal_path)

        _put_event_with_class(
            owner_client,
            owner,
            cal_id,
            "conf-owner-event",
            "Owner Sees This",
            "CONFIDENTIAL",
        )

        dav = CalDAVHTTPClient().get_dav_client(owner)
        found = False
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    if "Owner Sees This" in str(ev.data):
                        found = True
            except Exception:  # noqa: BLE001
                continue
        assert found, "Owner should see their own CONFIDENTIAL events"


class TestClassPrivateEnforcement:
    """CLASS:PRIVATE events should be completely hidden from shared users."""

    def test_private_event_hidden_from_sharee(self):
        """Sharee should NOT see CLASS:PRIVATE events at all."""
        org = factories.OrganizationFactory(external_id="class-priv-hide")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-cp")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-cp")
        cal_id = _get_cal_id(cal_path)

        # Create one PUBLIC and one PRIVATE event
        _put_event_with_class(
            owner_client, owner, cal_id, "public-event", "Visible Meeting", "PUBLIC"
        )
        _put_event_with_class(
            owner_client,
            owner,
            cal_id,
            "private-event",
            "Top Secret Private",
            "PRIVATE",
        )

        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        events = shared_cal.events()
        # PUBLIC event should be visible, PRIVATE should be hidden
        found_public = False
        for ev in events:
            data = str(ev.data)
            assert "Top Secret Private" not in data, (
                "SECURITY: PRIVATE event visible to sharee"
            )
            if "Visible Meeting" in data:
                found_public = True
        assert found_public, (
            "PUBLIC control event missing — test may be vacuously passing"
        )

    def test_private_event_visible_to_owner(self):
        """Owner should still see their own PRIVATE events."""
        org = factories.OrganizationFactory(external_id="class-priv-owner")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-cpo")
        cal_id = _get_cal_id(cal_path)

        _put_event_with_class(
            owner_client,
            owner,
            cal_id,
            "priv-owner-event",
            "Owner Private Event",
            "PRIVATE",
        )

        dav = CalDAVHTTPClient().get_dav_client(owner)
        found = False
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    if "Owner Private Event" in str(ev.data):
                        found = True
            except Exception:  # noqa: BLE001
                continue
        assert found, "Owner should see their own PRIVATE events"


class TestPublicClassVisibility:
    """CLASS:PUBLIC events should show full details to sharees (control test)."""

    def test_public_event_fully_visible_to_sharee(self):
        """PUBLIC events on shared calendars show full details."""
        org = factories.OrganizationFactory(external_id="class-pub-visible")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-cpv")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-cpv")
        cal_id = _get_cal_id(cal_path)

        _put_event_with_class(
            owner_client,
            owner,
            cal_id,
            "public-visible-event",
            "Public Team Lunch",
            "PUBLIC",
            description="At the Italian place",
            location="Restaurant",
        )

        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        found = False
        for ev in shared_cal.events():
            data = str(ev.data)
            if "Public Team Lunch" in data:
                found = True
                assert "Italian place" in data, "PUBLIC description should be visible"
                assert "Restaurant" in data, "PUBLIC location should be visible"
        assert found, "PUBLIC event should be visible to sharee"


class TestValarmStripping:
    """VALARM components should be stripped for non-owner shared calendar access."""

    def test_valarm_stripped_from_shared_calendar(self):
        """Sharee should NOT see the owner's VALARM reminders."""
        org = factories.OrganizationFactory(external_id="valarm-strip")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-va")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-va")
        cal_id = _get_cal_id(cal_path)

        _put_event_with_class(
            owner_client,
            owner,
            cal_id,
            "alarm-event",
            "Meeting with Alarm",
            "PUBLIC",
            valarm=True,
        )

        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        events = shared_cal.events()
        found = False
        for ev in events:
            data = str(ev.data)
            if "Meeting with Alarm" in data:
                found = True
                assert "VALARM" not in data, (
                    "VALARM should be stripped from shared calendar events"
                )
                assert "TRIGGER" not in data, (
                    "TRIGGER (part of VALARM) should be stripped"
                )
        assert found, "Target event not found in shared calendar"

    def test_valarm_preserved_for_owner(self):
        """Owner should still see their own VALARM reminders."""
        org = factories.OrganizationFactory(external_id="valarm-owner")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-vao")
        cal_id = _get_cal_id(cal_path)

        _put_event_with_class(
            owner_client,
            owner,
            cal_id,
            "alarm-owner-event",
            "Owner Alarm Event",
            "PUBLIC",
            valarm=True,
        )

        dav = CalDAVHTTPClient().get_dav_client(owner)
        found = False
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    if "Owner Alarm Event" in str(ev.data):
                        assert "VALARM" in str(ev.data), (
                            "Owner should see their own VALARM"
                        )
                        found = True
            except Exception:  # noqa: BLE001
                continue
        assert found, "Owner should see their alarm event"


class TestRRuleCap:
    """Unbounded RRULEs should get an UNTIL cap added automatically on write."""

    def test_unbounded_rrule_gets_until_cap(self):
        """An RRULE with no COUNT or UNTIL should get UNTIL added."""
        org = factories.OrganizationFactory(external_id="rrule-cap")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rc")
        cal_id = _get_cal_id(cal_path)

        dtstart = datetime.now() + timedelta(days=1)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:rrule-unbounded\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Weekly Forever\r\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        resp = owner_client.generic(
            "PUT",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/rrule-unbounded.ics",
            data=ical,
            content_type="text/calendar",
        )
        assert resp.status_code in (200, 201, 204)

        # Read it back and verify UNTIL was added
        http = CalDAVHTTPClient()
        data, _, _ = http.find_event_by_uid(owner, "rrule-unbounded")
        assert data is not None, "Event should exist"
        assert "UNTIL=" in data, (
            f"Unbounded RRULE should have UNTIL added. Got: {data[:500]}"
        )

    def test_bounded_rrule_with_count_unchanged(self):
        """An RRULE with COUNT should NOT be modified."""
        org = factories.OrganizationFactory(external_id="rrule-count")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rcc")
        cal_id = _get_cal_id(cal_path)

        dtstart = datetime.now() + timedelta(days=1)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:rrule-count\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Weekly 10 Times\r\n"
            "RRULE:FREQ=WEEKLY;COUNT=10;BYDAY=MO\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        resp = owner_client.generic(
            "PUT",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/rrule-count.ics",
            data=ical,
            content_type="text/calendar",
        )
        assert resp.status_code in (200, 201, 204)

        http = CalDAVHTTPClient()
        data, _, _ = http.find_event_by_uid(owner, "rrule-count")
        assert data is not None
        assert "COUNT=10" in data, "COUNT should be preserved"
        # UNTIL should NOT have been added
        assert "UNTIL=" not in data, (
            f"Bounded RRULE should not get UNTIL added. Got: {data[:500]}"
        )


class TestNonVeventComponentPrivacy:
    """``SharedCalendarPrivacyPlugin::applyRules`` must filter every
    scheduling component, not just VEVENT.

    Calendars are configured with ``supported-calendar-component-set =
    VEVENT`` and the HTTP PUT path enforces that. The internal-api
    import endpoint short-circuits to the backend so it must apply
    the same filter (see test_import_events.py for the import side),
    but as defense-in-depth the privacy plugin should ALSO strip
    VTODO/VJOURNAL components on shared-calendar reads in case any
    slip through (legacy data, future code paths, etc.).
    """

    def _vtodo_ics(self, uid, summary, description):
        return (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Privacy//EN\r\n"
            "BEGIN:VTODO\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"SUMMARY:{summary}\r\n"
            f"DESCRIPTION:{description}\r\n"
            "STATUS:NEEDS-ACTION\r\n"
            "CLASS:PRIVATE\r\n"
            "END:VTODO\r\n"
            "END:VCALENDAR\r\n"
        ).encode("utf-8")

    def test_vtodo_does_not_leak_to_sharee(self):  # pylint: disable=too-many-locals
        """A VTODO present on a shared calendar must NOT leak its
        SUMMARY/DESCRIPTION to a read-only sharee, even though the
        privacy plugin's per-component filter was historically only
        wired for VEVENT.

        We bypass the (correctly) blocking PUT path by using the
        internal-api import endpoint and a calendar that allows
        VTODO. Production calendars are VEVENT-only and the import
        endpoint filters them out, but the test mounts a deliberately
        permissive setup to exercise the privacy plugin in isolation.
        """
        org = factories.OrganizationFactory(external_id="vtodo-leak")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-vtodo")
        sharee, sharee_client, _ = _create_user_with_calendar(org, "sharee-vtodo")
        cal_id = _get_cal_id(cal_path)

        unique = uuid.uuid4().hex[:8]
        leak_text = f"Secret Personal Task {unique}"
        leak_desc = f"Buy gift for spouse {unique}"
        ics = self._vtodo_ics(
            f"privacy-vtodo-{unique}",
            leak_text,
            leak_desc,
        )

        # Plant the VTODO via the import endpoint. The default test
        # helper above creates calendars via the caldav library's
        # MKCALENDAR with no explicit component-set, which makes
        # SabreDAV fall back to its built-in default of
        # ``VEVENT,VTODO`` — so the VTODO is accepted here. Real
        # production calendars are VEVENT-only and would reject it
        # at the import filter (see test_import_events.py).
        importer = ICSImportService()
        result = importer.import_events(owner, cal_path, ics)
        if result.imported_count == 0:
            pytest.skip(
                "VTODO was filtered at import — leak path is closed at "
                "the import layer for this calendar."
            )

        share_resp = _share_calendar(owner_client, owner, cal_id, sharee.email, "read")
        assert share_resp.status_code in (200, 204), (
            f"Share failed: {share_resp.status_code} {share_resp.content[:500]}"
        )

        # Probe ALL of the sharee's calendars via calendar-query
        # REPORT — the privacy filter must strip the VTODO content
        # from any of them.
        dav_sharee = CalDAVHTTPClient().get_dav_client(sharee)
        sharee_cal_paths = [
            urlparse(str(cal.url)).path
            for cal in dav_sharee.principal().calendars()
            if urlparse(str(cal.url)).path
        ]
        assert sharee_cal_paths, (
            "Sharee has no calendars to probe — share didn't propagate."
        )

        report_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<C:calendar-query xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:prop><C:calendar-data/></D:prop>"
            '<C:filter><C:comp-filter name="VCALENDAR"/></C:filter>'
            "</C:calendar-query>"
        )
        for cal_path_to_probe in sharee_cal_paths:
            report_resp = sharee_client.generic(
                "REPORT",
                cal_path_to_probe,
                data=report_body,
                content_type="application/xml",
                HTTP_DEPTH="1",
            )
            report_text = report_resp.content.decode("utf-8", errors="ignore")
            assert leak_text not in report_text, (
                "SECURITY: VTODO SUMMARY leaked to sharee via "
                "calendar-query REPORT — privacy filter only iterates "
                f"VEVENT. Path={cal_path_to_probe}, "
                f"Body: {report_text[:1500]}"
            )
            assert leak_desc not in report_text, (
                "SECURITY: VTODO DESCRIPTION leaked to sharee. "
                f"Path={cal_path_to_probe}, Body: {report_text[:1500]}"
            )
