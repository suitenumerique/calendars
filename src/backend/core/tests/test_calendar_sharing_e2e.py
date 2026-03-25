"""E2E calendar sharing access rights tests against real SabreDAV.

Privilege levels: freebusy (busy/free only), read, read-write, admin.
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
    """Use local entitlements backend for all tests in this module."""
    settings.ENTITLEMENTS_BACKEND = (
        "core.entitlements.backends.local.LocalEntitlementsBackend"
    )
    settings.ENTITLEMENTS_BACKEND_PARAMETERS = {}
    get_entitlements_backend.cache_clear()
    yield
    get_entitlements_backend.cache_clear()


def _create_user_with_calendar(org, email_prefix):
    """Create a user with a calendar and return (user, client, calendar_path)."""
    user = factories.UserFactory(
        email=f"{email_prefix}@share-test.com", organization=org
    )
    client = APIClient()
    client.force_login(user)

    service = CalendarService()
    caldav_path = service.create_calendar(user, name=f"{email_prefix}'s Calendar")
    return user, client, caldav_path


def _get_cal_id(caldav_path):
    """Extract calendar ID from path like calendars/users/email/cal-id/."""
    parts = caldav_path.strip("/").split("/")
    return parts[-1] if len(parts) >= 4 else "default"


def _share_calendar_via_caldav(owner_client, owner, cal_id, sharee_email, privilege):
    """Share a calendar using CS:share POST via the CalDAV proxy."""
    privilege_xml = {
        "read": "<CS:read/>",
        "read-write": "<CS:read-write/>",
        "admin": "<CS:admin/>",
    }[privilege]

    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
        "<CS:set>"
        f"<D:href>mailto:{sharee_email}</D:href>"
        f"{privilege_xml}"
        "</CS:set>"
        "</CS:share>"
    )
    return owner_client.generic(
        "POST",
        f"/caldav/calendars/users/{owner.email}/{cal_id}/",
        data=body,
        content_type="application/xml",
    )


def _unshare_calendar(owner_client, owner, cal_id, sharee_email):
    """Unshare a calendar via CS:share POST with CS:remove."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
        "<CS:remove>"
        f"<D:href>mailto:{sharee_email}</D:href>"
        "</CS:remove>"
        "</CS:share>"
    )
    return owner_client.generic(
        "POST",
        f"/caldav/calendars/users/{owner.email}/{cal_id}/",
        data=body,
        content_type="application/xml",
    )


def _get_calendars(user):
    """Return all calendars for a user via the CalDAV Python library."""
    dav = CalDAVHTTPClient().get_dav_client(user)
    try:
        return dav.principal().calendars()
    except Exception:  # noqa: BLE001
        return []


def _get_calendar_urls(user):
    """Return the set of calendar URLs for a user."""
    return {str(cal.url) for cal in _get_calendars(user)}


def _share_and_find(owner_client, owner, cal_id, sharee, privilege):
    """Share a calendar and return the new shared calendar object.

    Compares calendars before/after sharing to identify the new one.
    This is reliable regardless of how SabreDAV names the proxy URL.
    """
    urls_before = _get_calendar_urls(sharee)

    resp = _share_calendar_via_caldav(
        owner_client, owner, cal_id, sharee.email, privilege
    )
    assert resp.status_code in (200, 204), (
        f"Share failed: {resp.status_code} "
        f"{resp.content.decode('utf-8', errors='ignore')[:500]}"
    )

    cals_after = _get_calendars(sharee)
    new_cals = [c for c in cals_after if str(c.url) not in urls_before]
    assert len(new_cals) == 1, (
        f"Expected exactly 1 new calendar after sharing, got {len(new_cals)}. "
        f"Before: {urls_before}, After: {[str(c.url) for c in cals_after]}"
    )
    return new_cals[0]


def _put_event(client, user_email, cal_id, event_uid, summary="Test Event"):
    """PUT a VCALENDAR event into a calendar via the CalDAV proxy."""
    dtstart = datetime.now() + timedelta(days=1)
    dtend = dtstart + timedelta(hours=1)
    ical = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{event_uid}\r\n"
        f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"SUMMARY:{summary}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return client.generic(
        "PUT",
        f"/caldav/calendars/users/{user_email}/{cal_id}/{event_uid}.ics",
        data=ical,
        content_type="text/calendar",
    )


def _get_event(client, user_email, cal_id, event_uid):
    """GET a specific event from a calendar."""
    return client.generic(
        "GET",
        f"/caldav/calendars/users/{user_email}/{cal_id}/{event_uid}.ics",
    )


def _delete_event(client, user_email, cal_id, event_uid):
    """DELETE a specific event from a calendar."""
    return client.generic(
        "DELETE",
        f"/caldav/calendars/users/{user_email}/{cal_id}/{event_uid}.ics",
    )


def _propfind_calendar(client, user_email, cal_id):
    """PROPFIND a calendar to check access."""
    body = (
        '<?xml version="1.0"?>'
        '<propfind xmlns="DAV:"><prop><displayname/></prop></propfind>'
    )
    return client.generic(
        "PROPFIND",
        f"/caldav/calendars/users/{user_email}/{cal_id}/",
        data=body,
        content_type="application/xml",
        HTTP_DEPTH="0",
    )


def _report_events(client, user_email, cal_id):
    """REPORT on a calendar to list events."""
    dtstart = datetime.now() - timedelta(days=30)
    dtend = datetime.now() + timedelta(days=30)
    body = (
        '<?xml version="1.0" encoding="utf-8" ?>'
        '<C:calendar-query xmlns:D="DAV:" '
        'xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<D:prop>"
        "<D:getetag/>"
        "<C:calendar-data/>"
        "</D:prop>"
        "<C:filter>"
        '<C:comp-filter name="VCALENDAR">'
        '<C:comp-filter name="VEVENT">'
        "<C:time-range "
        f'start="{dtstart.strftime("%Y%m%dT%H%M%SZ")}" '
        f'end="{dtend.strftime("%Y%m%dT%H%M%SZ")}"/>'
        "</C:comp-filter>"
        "</C:comp-filter>"
        "</C:filter>"
        "</C:calendar-query>"
    )
    return client.generic(
        "REPORT",
        f"/caldav/calendars/users/{user_email}/{cal_id}/",
        data=body,
        content_type="application/xml",
        HTTP_DEPTH="1",
    )


def _get_sharees(client, user_email, cal_id):
    """PROPFIND with CS:invite to get current sharees."""
    body = (
        '<?xml version="1.0"?>'
        '<propfind xmlns="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
        "<prop>"
        "<CS:invite/>"
        "</prop>"
        "</propfind>"
    )
    return client.generic(
        "PROPFIND",
        f"/caldav/calendars/users/{user_email}/{cal_id}/",
        data=body,
        content_type="application/xml",
        HTTP_DEPTH="0",
    )


class TestCalendarSharingSetup:
    """Test that sharing creates invite entries correctly."""

    def test_share_calendar_read(self):
        """Sharing with read privilege creates a sharee entry."""
        org = factories.OrganizationFactory(external_id="share-setup-read")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-r")
        sharee = factories.UserFactory(
            email="sharee-r@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        response = _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "read"
        )
        assert response.status_code in (200, 204), (
            f"Share failed: {response.status_code} "
            f"{response.content.decode('utf-8', errors='ignore')[:500]}"
        )

        # Verify sharee appears in invite list
        invite_resp = _get_sharees(owner_client, owner.email, cal_id)
        assert invite_resp.status_code == 207
        content = invite_resp.content.decode("utf-8", errors="ignore")
        assert sharee.email in content

    def test_share_calendar_read_write(self):
        """Sharing with read-write privilege creates a sharee entry."""
        org = factories.OrganizationFactory(external_id="share-setup-rw")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rw")
        sharee = factories.UserFactory(
            email="sharee-rw@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        response = _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "read-write"
        )
        assert response.status_code in (200, 204)

    def test_share_calendar_admin(self):
        """Sharing with admin privilege creates a sharee entry."""
        org = factories.OrganizationFactory(external_id="share-setup-admin")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-admin")
        sharee = factories.UserFactory(
            email="sharee-admin@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        response = _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "admin"
        )
        assert response.status_code in (200, 204)

    def test_unshare_calendar(self):
        """Unsharing removes the sharee entry."""
        org = factories.OrganizationFactory(external_id="share-setup-unshare")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-un")
        sharee = factories.UserFactory(
            email="sharee-un@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        # Share then unshare
        _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "read-write"
        )
        response = _unshare_calendar(owner_client, owner, cal_id, sharee.email)
        assert response.status_code in (200, 204)

    def test_share_privilege_returned_correctly_in_invite(self):
        """CS:invite PROPFIND returns the correct privilege for each share level."""
        org = factories.OrganizationFactory(external_id="share-priv-check")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-pc")
        cal_id = _get_cal_id(cal_path)

        for privilege in ["read", "read-write"]:
            sharee = factories.UserFactory(
                email=f"sharee-{privilege}@priv-check.com", organization=org
            )
            _share_calendar_via_caldav(
                owner_client, owner, cal_id, sharee.email, privilege
            )

        # PROPFIND CS:invite to check what SabreDAV stored
        invite_resp = _get_sharees(owner_client, owner.email, cal_id)
        assert invite_resp.status_code == 207
        content = invite_resp.content.decode("utf-8", errors="ignore")

        # The read-write sharee should have <cs:read-write/> in their access
        assert "read-write" in content.lower() or "readwrite" in content.lower(), (
            f"Expected read-write privilege in CS:invite response but got:\n"
            f"{content[:2000]}"
        )


class TestReadOnlySharing:
    """Verify read-only sharees can read events but cannot modify them.

    Uses the CalDAV Python library to access shared calendars, which goes
    directly to SabreDAV (bypassing the Django proxy). This tests the
    CalDAV ACL enforcement at the SabreDAV level.
    """

    def test_read_sharee_can_see_shared_calendar(self):
        """After sharing, the shared calendar appears in the sharee's home."""
        org = factories.OrganizationFactory(external_id="ro-see")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-ros")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-ros")
        cal_id = _get_cal_id(cal_path)

        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")
        assert shared_cal is not None

    def test_read_sharee_can_read_events(self):
        """Read-only sharee can read events from the shared calendar."""
        org = factories.OrganizationFactory(external_id="ro-read")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-ror")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-ror")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "ro-read-ev", "Shared Event")
        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        events = shared_cal.events()
        found = any("Shared Event" in str(ev.data) for ev in events)
        assert found, "Read sharee should see shared events"

    def test_read_sharee_cannot_create_event(self):
        """Read-only sharee CANNOT create events in the shared calendar."""
        org = factories.OrganizationFactory(external_id="ro-nocreate")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-roc")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-roc")
        cal_id = _get_cal_id(cal_path)

        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        dtstart = datetime.now() + timedelta(days=2)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VEVENT\r\nUID:ro-blocked-create\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Should Fail\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with pytest.raises(Exception):  # noqa: B017
            shared_cal.save_event(ical)

    def test_read_sharee_cannot_delete_event(self):
        """Read-only sharee CANNOT delete events from the shared calendar."""
        org = factories.OrganizationFactory(external_id="ro-nodelete")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rod")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-rod")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "ro-del-ev", "Protected")
        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        events = shared_cal.events()
        target = [ev for ev in events if "Protected" in str(ev.data)]
        assert len(target) == 1, "Should find the shared event"

        with pytest.raises(Exception):  # noqa: B017
            target[0].delete()

        # Verify it still exists
        http = CalDAVHTTPClient()
        data, _, _ = http.find_event_by_uid(owner, "ro-del-ev")
        assert data is not None, "Event should survive blocked delete"


class TestReadWriteSharing:
    """Verify read-write sharees can CRUD events but cannot perform admin ops.

    Uses CalDAV Python library for sharee operations (direct to SabreDAV).
    """

    def test_rw_sharee_can_read_events(self):
        """Read-write sharee can read events via shared calendar."""
        org = factories.OrganizationFactory(external_id="rw-read")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rwrd")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-rwrd")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "rw-read-ev", "RW Event")
        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read-write")

        events = shared_cal.events()
        found = any("RW Event" in str(ev.data) for ev in events)
        assert found, "RW sharee should see shared events"

    def test_rw_sharee_can_create_event(self):
        """Read-write sharee CAN create events in the shared calendar."""
        org = factories.OrganizationFactory(external_id="rw-create")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rwc")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-rwc")
        cal_id = _get_cal_id(cal_path)

        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read-write")

        dtstart = datetime.now() + timedelta(days=2)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VEVENT\r\nUID:rw-created-ev\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Created by Sharee\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        shared_cal.save_event(ical)

        http = CalDAVHTTPClient()
        data, _, _ = http.find_event_by_uid(owner, "rw-created-ev")
        assert data is not None, "Event created by RW sharee should exist"

    def test_rw_sharee_can_delete_event(self):
        """Read-write sharee CAN delete events from the shared calendar."""
        org = factories.OrganizationFactory(external_id="rw-delete")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rwd")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-rwd")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "rw-del-ev", "Doomed")
        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read-write")

        events = shared_cal.events()
        target = [ev for ev in events if "Doomed" in str(ev.data)]
        assert len(target) == 1, "Should find the doomed event"
        target[0].delete()

        http = CalDAVHTTPClient()
        data, _, _ = http.find_event_by_uid(owner, "rw-del-ev")
        assert data is None, "Deleted event should be gone"


class TestNoAccessSharing:
    """Verify that users without sharing cannot access calendars."""

    def test_non_shared_user_cannot_read_events(self):
        """A user who was NOT shared the calendar cannot GET events."""
        org = factories.OrganizationFactory(external_id="no-access-read")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-nar")
        stranger, stranger_client, _ = _create_user_with_calendar(org, "stranger-nar")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "private-event", "Private Event")

        # Stranger tries to GET the event (not shared)
        response = _get_event(stranger_client, owner.email, cal_id, "private-event")
        assert response.status_code in (403, 404), (
            f"Non-shared user should NOT be able to GET events, "
            f"got {response.status_code}"
        )

    def test_non_shared_user_cannot_create_events(self):
        """A non-shared user cannot PUT events into another user's calendar."""
        org = factories.OrganizationFactory(external_id="no-access-create")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-nac")
        stranger, stranger_client, _ = _create_user_with_calendar(org, "stranger-nac")
        cal_id = _get_cal_id(cal_path)

        response = _put_event(
            stranger_client, owner.email, cal_id, "intruder-event", "Intruder"
        )
        assert response.status_code in (403, 404), (
            f"Non-shared user should NOT be able to PUT events, "
            f"got {response.status_code}"
        )

    def test_non_shared_user_cannot_delete_events(self):
        """A non-shared user cannot DELETE events from another user's calendar."""
        org = factories.OrganizationFactory(external_id="no-access-del")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-nad")
        stranger, stranger_client, _ = _create_user_with_calendar(org, "stranger-nad")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "safe-event", "Safe Event")

        response = _delete_event(stranger_client, owner.email, cal_id, "safe-event")
        assert response.status_code in (403, 404), (
            f"Non-shared user should NOT be able to DELETE events, "
            f"got {response.status_code}"
        )

    def test_non_shared_user_cannot_report_events(self):
        """A non-shared user cannot REPORT on another user's calendar."""
        org = factories.OrganizationFactory(external_id="no-access-report")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-nart")
        stranger, stranger_client, _ = _create_user_with_calendar(org, "stranger-nart")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "hidden-event", "Hidden Event")

        response = _report_events(stranger_client, owner.email, cal_id)
        # Should be 403 or return empty — event data should not leak
        if response.status_code == 207:
            content = response.content.decode("utf-8", errors="ignore")
            assert "Hidden Event" not in content, (
                "Non-shared user should NOT see event data in REPORT"
            )
        else:
            assert response.status_code in (403, 404)


class TestPrivilegeEscalation:
    """Verify that sharing privilege changes are enforced correctly.

    Uses CalDAV Python library for sharee operations.
    """

    def test_downgrade_from_rw_to_read_blocks_write(self):
        """After downgrading from read-write to read, write should fail."""
        org = factories.OrganizationFactory(external_id="escalation-down")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-ed")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-ed")
        cal_id = _get_cal_id(cal_path)

        # Share as read-write and find the shared calendar
        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read-write")

        dtstart = datetime.now() + timedelta(days=3)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VEVENT\r\nUID:esc-rw-ev\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Writable\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        shared_cal.save_event(ical)  # Should succeed

        # Downgrade to read-only
        _share_calendar_via_caldav(owner_client, owner, cal_id, sharee.email, "read")

        # Sharee should no longer be able to write
        ical2 = ical.replace("esc-rw-ev", "esc-blocked-ev").replace(
            "Writable", "Blocked"
        )
        # Re-fetch the shared calendar to get updated ACL
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        cals = dav.principal().calendars()
        shared_cal2 = [c for c in cals if str(c.url) == str(shared_cal.url)][0]
        with pytest.raises(Exception):  # noqa: B017
            shared_cal2.save_event(ical2)

    def test_upgrade_from_read_to_rw_allows_write(self):
        """After upgrading from read to read-write, write should succeed."""
        org = factories.OrganizationFactory(external_id="escalation-up")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-eu")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-eu")
        cal_id = _get_cal_id(cal_path)

        # Share as read and find the shared calendar
        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        dtstart = datetime.now() + timedelta(days=4)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VEVENT\r\nUID:esc-up-ev\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Upgraded\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with pytest.raises(Exception):  # noqa: B017
            shared_cal.save_event(ical)

        # Upgrade to read-write
        _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "read-write"
        )

        # Now sharee can write — re-fetch to get updated ACL
        dav2 = CalDAVHTTPClient().get_dav_client(sharee)
        cals2 = dav2.principal().calendars()
        shared_cal2 = [c for c in cals2 if str(c.url) == str(shared_cal.url)][0]
        shared_cal2.save_event(ical)
        http = CalDAVHTTPClient()
        data, _, _ = http.find_event_by_uid(owner, "esc-up-ev")
        assert data is not None, "Upgraded sharee should create events"

    def test_revoke_access_removes_shared_calendar(self):
        """After unsharing, the shared calendar disappears from sharee's home."""
        org = factories.OrganizationFactory(external_id="escalation-revoke")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-er")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-er")
        cal_id = _get_cal_id(cal_path)

        # Count calendars before sharing
        cals_before_share = _get_calendars(sharee)
        count_before = len(cals_before_share)

        _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "read-write"
        )

        # Verify shared calendar appeared
        cals_after_share = _get_calendars(sharee)
        assert len(cals_after_share) > count_before, (
            "Shared calendar should appear after sharing"
        )

        # Unshare
        _unshare_calendar(owner_client, owner, cal_id, sharee.email)

        # Verify shared calendar is gone
        cals_after_revoke = _get_calendars(sharee)
        assert len(cals_after_revoke) == count_before, (
            "Shared calendar should be gone after revocation"
        )


class TestCrossOrgSharing:
    """Verify sharing works across organizations via CalDAV library."""

    def test_cross_org_read_sharing(self):
        """Owner in org A can share read access with user in org B."""
        org_a = factories.OrganizationFactory(external_id="xorg-share-a")
        org_b = factories.OrganizationFactory(external_id="xorg-share-b")
        owner, owner_client, cal_path = _create_user_with_calendar(org_a, "owner-xorg")
        sharee, _, _ = _create_user_with_calendar(org_b, "sharee-xorg")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "xorg-ev", "Cross-Org Event")
        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        events = shared_cal.events()
        found = any("Cross-Org Event" in str(ev.data) for ev in events)
        assert found, "Cross-org read sharee should see shared events"

    def test_cross_org_read_sharee_cannot_write(self):
        """Cross-org read sharee CANNOT create events."""
        org_a = factories.OrganizationFactory(external_id="xorg-nowrite-a")
        org_b = factories.OrganizationFactory(external_id="xorg-nowrite-b")
        owner, owner_client, cal_path = _create_user_with_calendar(org_a, "owner-xnw")
        sharee, _, _ = _create_user_with_calendar(org_b, "sharee-xnw")
        cal_id = _get_cal_id(cal_path)

        shared_cal = _share_and_find(owner_client, owner, cal_id, sharee, "read")

        dtstart = datetime.now() + timedelta(days=5)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n"
            "BEGIN:VEVENT\r\nUID:xorg-blocked\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Blocked\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with pytest.raises(Exception):  # noqa: B017
            shared_cal.save_event(ical)


def _share_as_freebusy(owner_client, owner, cal_id, sharee_email):
    """Share a calendar with freebusy-only access.

    This shares with CS:read privilege and sets a custom property on the
    calendar to mark it as freebusy-only. The FreeBusySharePlugin in
    SabreDAV reads this property and strips event details.
    """
    # Step 1: Share with read access
    resp = _share_calendar_via_caldav(owner_client, owner, cal_id, sharee_email, "read")
    assert resp.status_code in (200, 204), f"Share failed: {resp.status_code}"

    # Step 2: Set the freebusy custom property via PROPPATCH
    proppatch_body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propertyupdate xmlns:D="DAV:" '
        'xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
        "<D:set><D:prop>"
        "<LS:freebusy-access>true</LS:freebusy-access>"
        "</D:prop></D:set>"
        "</D:propertyupdate>"
    )
    resp = owner_client.generic(
        "PROPPATCH",
        f"/caldav/calendars/users/{owner.email}/{cal_id}/",
        data=proppatch_body,
        content_type="application/xml",
    )
    assert resp.status_code in (200, 207), (
        f"PROPPATCH failed: {resp.status_code} "
        f"{resp.content.decode('utf-8', errors='ignore')[:500]}"
    )
    return resp


class TestFreebusyEnforcement:
    """Verify that freebusy-only sharees cannot see event details.

    When a calendar is shared with the "freebusy" access level (CS:read
    privilege + access:freebusy summary marker), the sharee should only
    see that time slots are busy — NOT the event summary, description,
    attendees, or location.

    This is a SECURITY requirement: the owner explicitly chose to share
    only availability, not event content.
    """

    def test_freebusy_sharee_cannot_see_event_summary(self):
        """Freebusy sharee MUST NOT see the SUMMARY of events."""
        org = factories.OrganizationFactory(external_id="fb-enforce-summary")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbs")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-fbs")
        cal_id = _get_cal_id(cal_path)

        # Owner creates an event with a confidential title
        _put_event(
            owner_client,
            owner.email,
            cal_id,
            "fb-secret-event",
            "Confidential Board Meeting",
        )

        # Share as freebusy (CS:read + access:freebusy summary)
        _share_as_freebusy(owner_client, owner, cal_id, sharee.email)

        # Sharee reads events via CalDAV — MUST NOT see the summary
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    event_data = str(ev.data)
                    assert "Confidential Board Meeting" not in event_data, (
                        "SECURITY VIOLATION: Freebusy sharee can see event SUMMARY! "
                        f"Event data: {event_data[:500]}"
                    )
            except Exception as exc:
                if "Confidential Board Meeting" in str(exc):
                    raise
                continue

    def test_freebusy_sharee_cannot_see_event_description_or_location(self):
        """Freebusy sharee MUST NOT see DESCRIPTION or LOCATION."""
        org = factories.OrganizationFactory(external_id="fb-enforce-desc")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbd")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-fbd")
        cal_id = _get_cal_id(cal_path)

        dtstart = datetime.now() + timedelta(days=1)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:fb-secret-desc\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Meeting\r\n"
            "DESCRIPTION:Secret salary negotiation details\r\n"
            "LOCATION:CEO Office Room 42\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        owner_client.generic(
            "PUT",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/fb-secret-desc.ics",
            data=ical,
            content_type="text/calendar",
        )

        _share_as_freebusy(owner_client, owner, cal_id, sharee.email)

        dav = CalDAVHTTPClient().get_dav_client(sharee)
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    event_data = str(ev.data)
                    assert "Secret salary negotiation" not in event_data, (
                        "SECURITY VIOLATION: Freebusy sharee can see DESCRIPTION!"
                    )
                    assert "CEO Office Room 42" not in event_data, (
                        "SECURITY VIOLATION: Freebusy sharee can see LOCATION!"
                    )
            except Exception as exc:
                if "Secret salary" in str(exc) or "CEO Office" in str(exc):
                    raise
                continue

    def test_freebusy_sharee_can_see_busy_times(self):
        """Freebusy sharee SHOULD still see that time slots are busy."""
        org = factories.OrganizationFactory(external_id="fb-enforce-busy")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbb")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-fbb")
        cal_id = _get_cal_id(cal_path)

        _put_event(
            owner_client, owner.email, cal_id, "fb-busy-event", "Private Meeting"
        )

        _share_as_freebusy(owner_client, owner, cal_id, sharee.email)

        # Sharee should see at least one event/busy block
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        found_any_event = False
        for cal in dav.principal().calendars():
            try:
                events = cal.events()
                if len(events) > 0:
                    found_any_event = True
            except Exception:  # noqa: BLE001
                continue
        assert found_any_event, (
            "Freebusy sharee should see busy time blocks (even without details)"
        )

    def test_full_read_sharee_can_see_event_summary(self):
        """Full read sharee (not freebusy) SHOULD see event details.

        This is the control test — ensures we don't accidentally strip
        details from regular read-only sharees.
        """
        org = factories.OrganizationFactory(external_id="fb-enforce-control")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbc")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-fbc")
        cal_id = _get_cal_id(cal_path)

        _put_event(
            owner_client,
            owner.email,
            cal_id,
            "fb-visible-event",
            "Visible Meeting Title",
        )

        # Share as full read (NOT freebusy — no summary marker)
        _share_calendar_via_caldav(owner_client, owner, cal_id, sharee.email, "read")

        dav = CalDAVHTTPClient().get_dav_client(sharee)
        found = False
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    if "Visible Meeting Title" in str(ev.data):
                        found = True
            except Exception:  # noqa: BLE001
                continue
        assert found, "Full read sharee SHOULD see event summary (control test)"

    def test_freebusy_sharee_cannot_see_meet_url_or_custom_properties(self):
        """Freebusy sharee MUST NOT see Meet URLs, CONFERENCE, or X-properties.

        The whitelist approach means ANY property not in the allowed list
        is dropped — including future properties we might add.
        """
        org = factories.OrganizationFactory(external_id="fb-enforce-xprops")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbx")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-fbx")
        cal_id = _get_cal_id(cal_path)

        dtstart = datetime.now() + timedelta(days=1)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:fb-xprops-event\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Secret Strategy Session\r\n"
            "DESCRIPTION:Discussing layoffs\r\n"
            "LOCATION:Boardroom\r\n"
            "CONFERENCE:https://meet.example.com/secret-room-123\r\n"
            "URL:https://internal.example.com/agenda/42\r\n"
            "X-CUSTOM-FIELD:sensitive-internal-data\r\n"
            "ATTENDEE;CN=Alice:mailto:alice@example.com\r\n"
            "ORGANIZER;CN=Boss:mailto:boss@example.com\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        owner_client.generic(
            "PUT",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/fb-xprops-event.ics",
            data=ical,
            content_type="text/calendar",
        )

        _share_as_freebusy(owner_client, owner, cal_id, sharee.email)

        dav = CalDAVHTTPClient().get_dav_client(sharee)
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    data = str(ev.data)
                    # None of these should leak
                    assert "Secret Strategy Session" not in data, (
                        "SECURITY: SUMMARY leaked"
                    )
                    assert "Discussing layoffs" not in data, (
                        "SECURITY: DESCRIPTION leaked"
                    )
                    assert "Boardroom" not in data, "SECURITY: LOCATION leaked"
                    assert "meet.example.com" not in data, (
                        "SECURITY: CONFERENCE/Meet URL leaked"
                    )
                    assert "internal.example.com" not in data, "SECURITY: URL leaked"
                    assert "sensitive-internal-data" not in data, (
                        "SECURITY: X-CUSTOM-FIELD leaked"
                    )
                    assert "alice@example.com" not in data, "SECURITY: ATTENDEE leaked"
                    assert "boss@example.com" not in data, "SECURITY: ORGANIZER leaked"
                    # But DTSTART/DTEND/UID should be present
                    assert "DTSTART" in data, "DTSTART should be preserved"
                    assert "DTEND" in data, "DTEND should be preserved"
                    assert "Busy" in data, "SUMMARY:Busy should be present"
            except Exception as exc:
                if any(s in str(exc) for s in ["SECURITY", "DTSTART", "DTEND", "Busy"]):
                    raise
                continue

    def test_freebusy_sharee_ics_export_does_not_leak(self):
        """Freebusy details MUST NOT leak via ICSExportPlugin (?export)."""
        org = factories.OrganizationFactory(external_id="fb-export-leak")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbex")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-fbex")
        sharee_client = APIClient()
        sharee_client.force_login(sharee)
        cal_id = _get_cal_id(cal_path)

        _put_event(
            owner_client,
            owner.email,
            cal_id,
            "fb-export-event",
            "Export Secret Meeting",
        )
        _share_as_freebusy(owner_client, owner, cal_id, sharee.email)

        # Find the shared calendar's URI in the sharee's home
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        cals_before = {str(c.url) for c in dav.principal().calendars()}
        # The shared calendar was already created by _share_as_freebusy
        # Find it by looking at all calendars
        shared_uri = None
        for cal in dav.principal().calendars():
            cal_url = str(cal.url).rstrip("/")
            cal_parts = cal_url.split("/")
            if len(cal_parts) >= 4:
                # Check if this calendar has our event
                try:
                    evts = cal.events()
                    for e in evts:
                        if "fb-export-event" in str(e.url):
                            shared_uri = "/".join(cal_parts[-2:])
                            break
                except Exception:  # noqa: BLE001
                    continue
            if shared_uri:
                break

        assert shared_uri is not None, "Shared calendar URI must be discoverable"
        response = sharee_client.generic(
            "GET",
            f"/caldav/calendars/users/{shared_uri}/?export",
        )
        if response.status_code == 200:
            content = response.content.decode("utf-8", errors="ignore")
            assert "Export Secret Meeting" not in content, (
                "SECURITY: ICS export leaks event details for freebusy sharee!"
            )

    def test_freebusy_sharee_propfind_calendar_data_does_not_leak(self):
        """Freebusy details MUST NOT leak via PROPFIND with calendar-data."""
        org = factories.OrganizationFactory(external_id="fb-propfind-leak")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbpf")
        sharee, _, _ = _create_user_with_calendar(org, "sharee-fbpf")
        sharee_client = APIClient()
        sharee_client.force_login(sharee)
        cal_id = _get_cal_id(cal_path)

        _put_event(
            owner_client,
            owner.email,
            cal_id,
            "fb-propfind-event",
            "Propfind Secret Meeting",
        )
        _share_as_freebusy(owner_client, owner, cal_id, sharee.email)

        # Find shared calendar URL for the sharee
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    if "fb-propfind-event" in str(ev.url):
                        # Try PROPFIND with calendar-data on this event via proxy
                        event_path = str(ev.url)
                        # Strip the CalDAV server URL prefix to get relative path
                        if "/caldav/" in event_path:
                            event_path = event_path.split("/caldav/", 1)[1]
                        response = sharee_client.generic(
                            "PROPFIND",
                            f"/caldav/{event_path}",
                            data=(
                                '<?xml version="1.0"?>'
                                '<propfind xmlns="DAV:" '
                                'xmlns:C="urn:ietf:params:xml:ns:caldav">'
                                "<prop><C:calendar-data/></prop>"
                                "</propfind>"
                            ),
                            content_type="application/xml",
                            HTTP_DEPTH="0",
                        )
                        if response.status_code == 207:
                            content = response.content.decode("utf-8", errors="ignore")
                            assert "Propfind Secret Meeting" not in content, (
                                "SECURITY: PROPFIND calendar-data leaks event details "
                                "for freebusy sharee!"
                            )
                        return
            except Exception:  # noqa: BLE001
                continue

    def test_freebusy_sharee_cannot_copy_event(self):
        """Freebusy sharee MUST NOT be able to COPY events to their own calendar."""
        org = factories.OrganizationFactory(external_id="fb-copy-block")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbcp")
        sharee, _, sharee_cal_path = _create_user_with_calendar(org, "sharee-fbcp")
        sharee_client = APIClient()
        sharee_client.force_login(sharee)
        cal_id = _get_cal_id(cal_path)
        sharee_cal_id = _get_cal_id(sharee_cal_path)

        _put_event(
            owner_client, owner.email, cal_id, "fb-copy-event", "Copyable Secret"
        )
        _share_as_freebusy(owner_client, owner, cal_id, sharee.email)

        # Find the shared event URL
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        event_url = None
        for cal in dav.principal().calendars():
            try:
                for ev in cal.events():
                    if "fb-copy-event" in str(ev.url):
                        event_url = str(ev.url)
                        break
            except Exception:  # noqa: BLE001
                continue
            if event_url:
                break

        assert event_url is not None, "Shared event URL must be discoverable"

        # Try to COPY to the sharee's own calendar via proxy
        src_path = event_url
        if "/caldav/" in src_path:
            src_path = src_path.split("/caldav/", 1)[1]
        dest_path = (
            f"/caldav/calendars/users/{sharee.email}/{sharee_cal_id}/copied-event.ics"
        )
        response = sharee_client.generic(
            "COPY",
            f"/caldav/{src_path}",
            HTTP_DESTINATION=dest_path,
        )
        assert response.status_code in (403, 409), (
            f"SECURITY: COPY from freebusy calendar should be blocked, "
            f"got {response.status_code}"
        )
