"""E2E tests for CLASS enforcement and VALARM stripping on shared calendars.

Tests that CLASS:PRIVATE hides events entirely, CLASS:CONFIDENTIAL shows
only time blocks, and VALARM components are stripped for non-owners.
Requires: CalDAV server running.
"""

# pylint: disable=no-member,broad-exception-caught,unused-variable,too-many-lines

from datetime import datetime, timedelta

import pytest
from rest_framework.test import APIClient

from core import factories
from core.entitlements.factory import get_entitlements_backend
from core.services.caldav_service import CalDAVHTTPClient, CalendarService

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
                assert "Secret Board Meeting" not in data, (
                    "SECURITY: CONFIDENTIAL event SUMMARY visible to sharee"
                )
                assert "Discussing layoffs" not in data, (
                    "SECURITY: CONFIDENTIAL event DESCRIPTION visible to sharee"
                )
                assert "CEO Suite" not in data, (
                    "SECURITY: CONFIDENTIAL event LOCATION visible to sharee"
                )
                assert "Busy" in data, "CONFIDENTIAL event should show as 'Busy'"
                assert "DTSTART" in data, "Time info should be preserved"
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
