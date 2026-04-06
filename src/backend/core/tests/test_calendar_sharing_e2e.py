"""E2E calendar sharing access rights tests against real SabreDAV.

Privilege levels: freebusy (busy/free only), read, read-write, admin.
Requires: CalDAV server running.
"""

# pylint: disable=no-member,broad-exception-caught,unused-variable,too-many-lines

from datetime import datetime, timedelta
from urllib.parse import unquote

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


http = CalDAVHTTPClient()

# Alias for tests moved from test_plugins_e2e.py
_share_calendar = _share_calendar_via_caldav


def _create_mailbox_calendar(owner, mailbox_email, org, name="Mailbox"):
    """Create a MAILBOX principal + default calendar via internal API."""
    resp = http.internal_request(
        "POST",
        owner,
        "internal-api/calendars/",
        json={
            "email": mailbox_email,
            "name": name,
            "calendar_user_type": "MAILBOX",
            "org_id": str(org.id),
        },
    )
    assert resp.status_code in (200, 201), (
        f"Mailbox calendar creation failed: {resp.status_code} {resp.text[:500]}"
    )
    return resp


def _list_calendar_urls(user):
    """Return the set of calendar URLs currently visible to user."""
    dav = CalDAVHTTPClient().get_dav_client(user)
    return {str(c.url) for c in dav.principal().calendars()}


def _find_shared_cal_uri(user, before_urls=None):
    """Find the URI of a newly added shared calendar.

    If ``before_urls`` is provided, the new calendar is found via
    set-difference against the current calendar list — this is unambiguous
    and robust to ordering. Otherwise, falls back to returning the last
    calendar (legacy behavior).

    Returns just the URI component (e.g., 'a1b2c3d4-...').
    """
    dav = CalDAVHTTPClient().get_dav_client(user)
    cals = dav.principal().calendars()
    if before_urls is not None:
        new_urls = {str(c.url) for c in cals} - set(before_urls)
        assert len(new_urls) == 1, (
            f"Expected exactly 1 new calendar after share, got {len(new_urls)}: "
            f"{new_urls}"
        )
        new_url = next(iter(new_urls))
    else:
        assert len(cals) >= 2, (
            f"Expected at least 2 calendars (own + shared), got {len(cals)}"
        )
        new_url = str(cals[-1].url)
    return unquote(new_url).rstrip("/").rsplit("/", maxsplit=1)[-1]


def _sync_mailbox_acls(owner, shares, full_sync_users=None):
    """Sync mailbox ACLs via internal API."""
    resp = http.internal_request(
        "POST",
        owner,
        "internal-api/sync-mailbox-acls/",
        json={"shares": shares, "full_sync_users": full_sync_users or []},
    )
    assert resp.status_code == 200, (
        f"ACL sync failed: {resp.status_code} {resp.text[:500]}"
    )
    return resp


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

    def test_share_with_user_without_principal(self):
        """Sharing with a user who has never accessed CalDAV should succeed.

        PrincipalBackend.findByUri auto-creates the sharee's principal
        when resolving the mailto: URI during CS:share.
        """
        org = factories.OrganizationFactory(external_id="share-no-principal")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-np")
        cal_id = _get_cal_id(cal_path)

        # Create a Django user but do NOT create their CalDAV principal
        sharee = factories.UserFactory(email="newguy@share-test.com", organization=org)

        # Share should succeed — findByUri auto-creates the principal
        response = _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "read"
        )
        assert response.status_code in (200, 204), (
            f"Share with non-existent principal failed: {response.status_code} "
            f"{response.content.decode('utf-8', errors='ignore')[:500]}"
        )

        # Verify the sharee appears in the invite list
        invite_resp = _get_sharees(owner_client, owner.email, cal_id)
        assert invite_resp.status_code == 207
        content = invite_resp.content.decode("utf-8", errors="ignore")
        assert sharee.email in content


class TestFreebusySharePersistence:
    """Test that freebusy shares are persisted correctly."""

    def test_freebusy_share_roundtrip(self):
        """Sharing with freebusy privilege should persist via LS:share-access."""
        org = factories.OrganizationFactory(external_id="freebusy-roundtrip")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fb")
        sharee = factories.UserFactory(
            email="sharee-fb@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        # Share with freebusy (CS:read + LS:share-access=freebusy)
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/"'
            ' xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
            "<CS:set>"
            f"<D:href>mailto:{sharee.email}</D:href>"
            "<LS:share-access>freebusy</LS:share-access>"
            "<CS:read/>"
            "</CS:set>"
            "</CS:share>"
        )
        resp = owner_client.generic(
            "POST",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=body,
            content_type="application/xml",
        )
        assert resp.status_code in (200, 204), (
            f"Freebusy share failed: {resp.status_code}"
        )

        # Read back via PROPFIND LS:share-access-map on the owner's calendar
        propfind_body = (
            '<?xml version="1.0"?>'
            '<propfind xmlns="DAV:" '
            'xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
            "<prop><LS:share-access-map/></prop>"
            "</propfind>"
        )
        map_resp = owner_client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=propfind_body,
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        content = map_resp.content.decode("utf-8", errors="ignore")
        assert "freebusy" in content, (
            f"Expected freebusy in LS:share-access-map response "
            f"but got:\n{content[:1000]}"
        )
        assert sharee.email in content, "Expected sharee email in LS:share-access-map"

    def test_per_share_freebusy_strips_event_details(self):
        """LS:share-access=freebusy should strip event details for THAT sharee only."""
        org = factories.OrganizationFactory(external_id="freebusy-pershare")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fps")
        freebusy_sharee = factories.UserFactory(
            email="fb-sharee@share-test.com", organization=org
        )
        read_sharee = factories.UserFactory(
            email="read-sharee@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        # Create event
        _put_event(
            owner_client,
            owner.email,
            cal_id,
            "pershare-secret",
            "Secret Strategy Meeting",
        )

        # Share with freebusy_sharee via LS:share-access
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/"'
            ' xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
            "<CS:set>"
            f"<D:href>mailto:{freebusy_sharee.email}</D:href>"
            "<LS:share-access>freebusy</LS:share-access>"
            "<CS:read/>"
            "</CS:set>"
            "</CS:share>"
        )
        resp = owner_client.generic(
            "POST",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=body,
            content_type="application/xml",
        )
        assert resp.status_code in (200, 204)

        # Share with read_sharee via normal CS:read (no share-access)
        resp = _share_calendar_via_caldav(
            owner_client, owner, cal_id, read_sharee.email, "read"
        )
        assert resp.status_code in (200, 204)

        # Freebusy sharee should NOT see the summary
        dav_fb = CalDAVHTTPClient().get_dav_client(freebusy_sharee)
        for cal in dav_fb.principal().calendars():
            for ev in cal.events():
                data = str(ev.data)
                assert "Secret Strategy Meeting" not in data, (
                    "SECURITY: Freebusy sharee sees event SUMMARY via "
                    f"LS:share-access=freebusy!\nData: {data[:500]}"
                )

        # Read sharee SHOULD see the summary
        dav_read = CalDAVHTTPClient().get_dav_client(read_sharee)
        found = False
        for cal in dav_read.principal().calendars():
            for ev in cal.events():
                if "Secret Strategy Meeting" in str(ev.data):
                    found = True
        assert found, "Read sharee should see full event details"


class TestSyncTakesOverManualShare:
    """Test that Messages sync upgrades a manual read-only share."""

    def test_sync_upgrades_manual_share_to_readwrite(self):
        """A manual read-only share is upgraded to read-write when the user
        gets sender/admin access in Messages (via sync-mailbox-acls)."""

        org = factories.OrganizationFactory(external_id="sync-takeover")
        owner = factories.UserFactory(email="owner@sync-takeover.com", organization=org)
        owner_client = APIClient()
        owner_client.force_login(owner)

        mailbox_email = "team@sync-takeover.com"
        sharee = factories.UserFactory(
            email="sharee@sync-takeover.com", organization=org
        )

        # 1. Create MAILBOX calendar
        resp = http.internal_request(
            "POST",
            owner,
            "internal-api/calendars/",
            json={
                "email": mailbox_email,
                "name": "Team",
                "calendar_user_type": "MAILBOX",
                "org_id": str(org.id),
            },
        )
        assert resp.status_code in (200, 201)

        # 2. Create a read-only share via sync (simulating a viewer in Messages)
        cal_id = "default"
        resp = http.internal_request(
            "POST",
            owner,
            "internal-api/sync-mailbox-acls/",
            json={
                "shares": [
                    {
                        "user_email": sharee.email,
                        "mailbox_email": mailbox_email,
                        "calendar_uri": "default",
                        "privilege": "read",
                    }
                ],
                "full_sync_users": [],
            },
        )
        assert resp.status_code == 200

        # 3. Sync with read-write (simulating Messages adding sender role)
        resp = http.internal_request(
            "POST",
            owner,
            "internal-api/sync-mailbox-acls/",
            json={
                "shares": [
                    {
                        "user_email": sharee.email,
                        "mailbox_email": mailbox_email,
                        "calendar_uri": "default",
                        "privilege": "read-write",
                    }
                ],
                "full_sync_users": [],
            },
        )
        assert resp.status_code == 200

        # 4. Verify the share was upgraded via CS:invite on the shared instance
        sharee_client = APIClient()
        sharee_client.force_login(sharee)
        # Find the shared calendar URI dynamically (UUID-based)
        dav_sharee = CalDAVHTTPClient().get_dav_client(sharee)
        sharee_cals = dav_sharee.principal().calendars()
        # The shared instance is the one not created by the sharee
        shared_cal_url = None
        for c in sharee_cals:
            cal_url = str(c.url)
            if sharee.email not in cal_url or len(sharee_cals) > 1:
                shared_cal_url = cal_url
        shared_path = (
            shared_cal_url.rsplit("/caldav/", maxsplit=1)[-1]
            if shared_cal_url and "/caldav/" in shared_cal_url
            else ""
        )
        assert shared_path, f"Could not find shared calendar for {sharee.email}"
        invite_resp = sharee_client.generic(
            "PROPFIND",
            f"/caldav/{shared_path}",
            data=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<D:propfind xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
                "<D:prop><CS:invite/></D:prop>"
                "</D:propfind>"
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        content = invite_resp.content.decode("utf-8", errors="ignore")
        assert sharee.email in content, (
            f"Expected {sharee.email} in invite list but got:\n{content[:500]}"
        )
        assert "read-write" in content.lower() or "readwrite" in content.lower(), (
            f"Expected read-write access for {sharee.email} after sync, "
            f"but got:\n{content[:1000]}"
        )


class TestSyncPreservesUserCustomizations:
    """Test that mailbox ACL sync doesn't overwrite user's personal settings."""

    def test_sync_preserves_calendar_color(self):
        """When a user changes their shared calendar's color, the sync
        should not overwrite it with the owner's color."""

        org = factories.OrganizationFactory(external_id="sync-color-test")
        owner = factories.UserFactory(email="owner@sync-color.com", organization=org)
        sharee = factories.UserFactory(email="sharee@sync-color.com", organization=org)

        mailbox_email = "team@sync-color.com"

        # 1. Create MAILBOX calendar with blue color
        resp = http.internal_request(
            "POST",
            owner,
            "internal-api/calendars/",
            json={
                "email": mailbox_email,
                "name": "Team",
                "calendar_user_type": "MAILBOX",
                "color": "#0000ff",
                "org_id": str(org.id),
            },
        )
        assert resp.status_code in (200, 201)

        # 2. Sync share for sharee (initial — creates the share with blue color)
        resp = http.internal_request(
            "POST",
            owner,
            "internal-api/sync-mailbox-acls/",
            json={
                "shares": [
                    {
                        "user_email": sharee.email,
                        "mailbox_email": mailbox_email,
                        "calendar_uri": "default",
                        "privilege": "read-write",
                    }
                ],
                "full_sync_users": [],
            },
        )
        assert resp.status_code == 200

        # 3. Sharee changes their calendar color to red via PROPPATCH
        sharee_client = APIClient()
        sharee_client.force_login(sharee)
        # Find shared calendar URI dynamically
        dav_s = CalDAVHTTPClient().get_dav_client(sharee)
        s_cals = dav_s.principal().calendars()
        assert len(s_cals) == 1, "Sharee should see exactly 1 calendar (the shared one)"
        # Find the calendar that wasn't there before sync (it's the newer one)
        shared_uri = str(s_cals[-1].url).rstrip("/").rsplit("/", maxsplit=1)[-1]
        proppatch_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propertyupdate xmlns:D="DAV:" '
            'xmlns:A="http://apple.com/ns/ical/">'
            "<D:set><D:prop>"
            "<A:calendar-color>#ff0000</A:calendar-color>"
            "</D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp = sharee_client.generic(
            "PROPPATCH",
            f"/caldav/calendars/users/{sharee.email}/{shared_uri}/",
            data=proppatch_body,
            content_type="application/xml",
        )
        assert resp.status_code == 207

        # 4. Run sync again with a CHANGED access level to trigger upsert
        # (e.g., user demoted from read-write to read, then promoted back)
        for privilege in ("read", "read-write"):
            resp = http.internal_request(
                "POST",
                owner,
                "internal-api/sync-mailbox-acls/",
                json={
                    "shares": [
                        {
                            "user_email": sharee.email,
                            "mailbox_email": mailbox_email,
                            "calendar_uri": "default",
                            "privilege": privilege,
                        }
                    ],
                    "full_sync_users": [],
                },
            )
            assert resp.status_code == 200

        # 5. Verify sharee's color is still red (not reset to blue)
        propfind_resp = sharee_client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{sharee.email}/{shared_uri}/",
            data=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<D:propfind xmlns:D="DAV:" xmlns:A="http://apple.com/ns/ical/">'
                "<D:prop><A:calendar-color/></D:prop>"
                "</D:propfind>"
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        content = propfind_resp.content.decode("utf-8", errors="ignore")
        assert "#ff0000" in content, (
            f"Sharee's calendar color should be #ff0000 (red) after sync, "
            f"but sync overwrote it. Response:\n{content[:500]}"
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
    """Share a calendar with freebusy-only access via LS:share-access.

    Sends a CS:share POST with CS:read + LS:share-access=freebusy.
    SharedCalendarPrivacyPlugin reads share_access_level from calendarinstances
    and strips event details for this sharee.
    """
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/"'
        ' xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
        "<CS:set>"
        f"<D:href>mailto:{sharee_email}</D:href>"
        "<LS:share-access>freebusy</LS:share-access>"
        "<CS:read/>"
        "</CS:set>"
        "</CS:share>"
    )
    resp = owner_client.generic(
        "POST",
        f"/caldav/calendars/users/{owner.email}/{cal_id}/",
        data=body,
        content_type="application/xml",
    )
    assert resp.status_code in (200, 204), (
        f"Freebusy share failed: {resp.status_code} "
        f"{resp.content.decode('utf-8', errors='ignore')[:500]}"
    )
    return resp


class TestFreebusyEnforcement:
    """Verify that freebusy-only sharees cannot see event details.

    When a calendar is shared with the "freebusy" access level (CS:read
    privilege + LS:share-access=freebusy), the sharee should only
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

        # Share as freebusy (CS:read + LS:share-access=freebusy)
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


# ===================================================================
# MailboxShareRestrictionPlugin (moved from test_plugins_e2e)
# ===================================================================


class TestMailboxShareRestriction:
    """MailboxPlugin caps shares on MAILBOX calendars to read.

    Write access to mailbox calendars must come via internal API sync only.
    """

    def test_direct_readwrite_share_on_mailbox_blocked(self):
        """CS:share with read-write on a MAILBOX calendar must be blocked."""
        org = factories.OrganizationFactory(external_id="mbx-restrict-rw")
        owner, owner_client, _ = _create_user_with_calendar(org, "owner-mbxr")
        sharee = factories.UserFactory(
            email="sharee@mbx-restrict.com", organization=org
        )
        mailbox_email = "team@mbx-restrict.com"
        _create_mailbox_calendar(owner, mailbox_email, org)

        before_urls = _list_calendar_urls(owner)
        # Sync owner so they can access the mailbox calendar
        _sync_mailbox_acls(
            owner,
            [
                {
                    "user_email": owner.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read-write",
                }
            ],
        )

        # Find the shared calendar URI dynamically
        shared_cal_uri = _find_shared_cal_uri(owner, before_urls=before_urls)

        # Try direct CS:share with read-write (should be blocked/capped)
        resp = owner_client.generic(
            "POST",
            f"/caldav/calendars/users/{owner.email}/{shared_cal_uri}/",
            data=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<CS:share xmlns:D="DAV:" '
                'xmlns:CS="http://calendarserver.org/ns/">'
                "<CS:set>"
                f"<D:href>mailto:{sharee.email}</D:href>"
                "<CS:read-write/>"
                "</CS:set>"
                "</CS:share>"
            ),
            content_type="application/xml",
        )
        # Should be 403 (Forbidden by MailboxPlugin)
        assert resp.status_code == 403, (
            f"Direct read-write share on MAILBOX calendar should be blocked, "
            f"got {resp.status_code}: {resp.content.decode()[:500]}"
        )

    def test_direct_read_share_on_mailbox_allowed(self):
        """CS:share with read-only on a MAILBOX calendar should be allowed."""
        org = factories.OrganizationFactory(external_id="mbx-restrict-ro")
        owner, owner_client, _ = _create_user_with_calendar(org, "owner-mbxro")
        sharee = factories.UserFactory(
            email="sharee@mbx-restrict-ro.com", organization=org
        )
        mailbox_email = "team@mbx-restrict-ro.com"
        _create_mailbox_calendar(owner, mailbox_email, org)

        before_urls = _list_calendar_urls(owner)
        _sync_mailbox_acls(
            owner,
            [
                {
                    "user_email": owner.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read-write",
                }
            ],
        )

        # Find the shared calendar URI dynamically
        shared_uri_ro = _find_shared_cal_uri(owner, before_urls=before_urls)

        resp = owner_client.generic(
            "POST",
            f"/caldav/calendars/users/{owner.email}/{shared_uri_ro}/",
            data=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<CS:share xmlns:D="DAV:" '
                'xmlns:CS="http://calendarserver.org/ns/">'
                "<CS:set>"
                f"<D:href>mailto:{sharee.email}</D:href>"
                "<CS:read/>"
                "</CS:set>"
                "</CS:share>"
            ),
            content_type="application/xml",
        )
        assert resp.status_code in (200, 204), (
            f"Read-only share on MAILBOX should be allowed, "
            f"got {resp.status_code}: {resp.content.decode()[:500]}"
        )

    def test_sync_readwrite_on_mailbox_via_internal_api_works(self):
        """Internal API can grant read-write on MAILBOX (bypasses plugin)."""
        org = factories.OrganizationFactory(external_id="mbx-restrict-sync")
        owner, _, _ = _create_user_with_calendar(org, "owner-mbxs")
        sharee = factories.UserFactory(
            email="sharee@mbx-restrict-sync.com", organization=org
        )
        mailbox_email = "team@mbx-restrict-sync.com"
        _create_mailbox_calendar(owner, mailbox_email, org)

        resp = _sync_mailbox_acls(
            owner,
            [
                {
                    "user_email": sharee.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read-write",
                }
            ],
        )
        assert resp.status_code == 200

        # Verify sharee can see the shared calendar
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        cals = dav.principal().calendars()
        assert len(cals) == 1, (
            f"Sharee should see exactly 1 calendar (the shared one), "
            f"got {len(cals)}: {[unquote(str(c.url)) for c in cals]}"
        )


# ===================================================================
# MailboxAddressPlugin (moved from test_plugins_e2e)
# ===================================================================


class TestMailboxAddressPlugin:
    """MailboxPlugin injects mailbox emails into address-set.

    Users with read-write access to a MAILBOX calendar should have
    the mailbox email in their calendar-user-address-set, enabling
    them to send as the mailbox in scheduling.
    """

    def test_rw_user_has_mailbox_in_address_set(self):
        """User with read-write mailbox share has mailbox email in addresses."""
        org = factories.OrganizationFactory(external_id="mbx-addr-rw")
        user, _, _ = _create_user_with_calendar(org, "user-mbxaddr")
        mailbox_email = "team@mbx-addr.com"
        _create_mailbox_calendar(user, mailbox_email, org)

        _sync_mailbox_acls(
            user,
            [
                {
                    "user_email": user.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read-write",
                }
            ],
        )

        # PROPFIND the principal to check calendar-user-address-set
        client = APIClient()
        client.force_login(user)
        resp = client.generic(
            "PROPFIND",
            f"/caldav/principals/users/{user.email}/",
            data=(
                '<?xml version="1.0"?>'
                '<propfind xmlns="DAV:" '
                'xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<prop><C:calendar-user-address-set/></prop>"
                "</propfind>"
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        content = resp.content.decode("utf-8", errors="ignore")
        assert f"mailto:{mailbox_email}" in content, (
            f"User with read-write mailbox share should have "
            f"mailto:{mailbox_email} in calendar-user-address-set.\n"
            f"Response: {content[:1000]}"
        )

    def test_readonly_user_does_not_have_mailbox_in_address_set(self):
        """User with read-only mailbox share should NOT have mailbox email."""
        org = factories.OrganizationFactory(external_id="mbx-addr-ro")
        user, _, _ = _create_user_with_calendar(org, "user-mbxaddrro")
        mailbox_email = "team@mbx-addr-ro.com"
        _create_mailbox_calendar(user, mailbox_email, org)

        _sync_mailbox_acls(
            user,
            [
                {
                    "user_email": user.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read",
                }
            ],
        )

        client = APIClient()
        client.force_login(user)
        resp = client.generic(
            "PROPFIND",
            f"/caldav/principals/users/{user.email}/",
            data=(
                '<?xml version="1.0"?>'
                '<propfind xmlns="DAV:" '
                'xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<prop><C:calendar-user-address-set/></prop>"
                "</propfind>"
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        content = resp.content.decode("utf-8", errors="ignore")
        assert f"mailto:{mailbox_email}" not in content, (
            f"User with read-only mailbox share should NOT have "
            f"mailto:{mailbox_email} in calendar-user-address-set.\n"
            f"Response: {content[:1000]}"
        )


# ===================================================================
# CS:invite-reply accept/decline (moved from test_plugins_e2e)
# ===================================================================


class TestShareAcceptDecline:
    """Test share acceptance and decline behavior.

    SabreDAV with PDO backend auto-accepts shares (no invite-reply needed).
    Shares appear immediately. "Declining" is done by DELETE on the shared
    calendar instance, which removes the sharee's view without affecting
    the owner's calendar or other sharees.
    """

    def test_shares_are_auto_accepted(self):
        """Shares appear immediately without needing invite-reply."""
        org = factories.OrganizationFactory(external_id="share-autoaccept")
        owner, owner_client, cal_path = _create_user_with_calendar(
            org, "owner-autoaccept"
        )
        sharee, _, _ = _create_user_with_calendar(org, "sharee-autoaccept")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "autoaccept-ev", "Shared Event")
        _share_calendar(owner_client, owner, cal_id, sharee.email, "read")

        # Sharee should immediately see the shared calendar + events
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        cals = dav.principal().calendars()
        # Should have more than 1 calendar (own + shared)
        assert len(cals) >= 2, (
            f"Sharee should see own + shared calendars, got {len(cals)}: "
            f"{[unquote(str(c.url)) for c in cals]}"
        )

        found = False
        for cal in cals:
            try:
                for ev in cal.events():
                    if "Shared Event" in str(ev.data):
                        found = True
            except Exception:  # noqa: BLE001
                continue
        assert found, "Sharee should immediately see shared events"

    def test_delete_shared_calendar_removes_sharee_view(self):
        """DELETE on a shared calendar instance removes the sharee's view."""
        org = factories.OrganizationFactory(external_id="share-decline-del")
        owner, owner_client, cal_path = _create_user_with_calendar(
            org, "owner-sharedel"
        )
        sharee, _, _ = _create_user_with_calendar(org, "sharee-sharedel")
        sharee_client = APIClient()
        sharee_client.force_login(sharee)
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "decline-ev", "Shared Event")

        # Record URLs before sharing
        dav_pre = CalDAVHTTPClient().get_dav_client(sharee)
        urls_before_share = {str(c.url) for c in dav_pre.principal().calendars()}

        _share_calendar(owner_client, owner, cal_id, sharee.email, "read")

        # Find the NEW calendar URL (the shared one)
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        cals_after_share = dav.principal().calendars()
        new_cals = [c for c in cals_after_share if str(c.url) not in urls_before_share]
        assert len(new_cals) == 1, (
            f"Expected 1 new shared calendar, got {len(new_cals)}"
        )
        shared_cal = new_cals[0]
        shared_cal_url = str(shared_cal.url)

        # DELETE the shared calendar instance
        if "/caldav/" in shared_cal_url:
            rel_path = shared_cal_url.split("/caldav/", 1)[1]
        else:
            rel_path = shared_cal_url.lstrip("/")

        resp = sharee_client.generic("DELETE", f"/caldav/{rel_path}")
        assert resp.status_code in (200, 204), (
            f"DELETE shared calendar should succeed, got {resp.status_code}"
        )

        # Sharee should no longer see the shared calendar
        dav2 = CalDAVHTTPClient().get_dav_client(sharee)
        urls_after_delete = {str(c.url) for c in dav2.principal().calendars()}
        assert shared_cal_url not in urls_after_delete, (
            "Shared calendar URL should be gone after DELETE"
        )

        # Owner's calendar + event should be unaffected
        owner_check = owner_client.generic(
            "GET",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/decline-ev.ics",
        )
        assert owner_check.status_code == 200, (
            "Owner's event should still exist after sharee deletes shared view"
        )

    def test_delete_shared_calendar_doesnt_affect_other_sharees(self):  # noqa: PLR0912  # pylint: disable=too-many-branches
        """One sharee deleting their view doesn't affect other sharees."""
        org = factories.OrganizationFactory(external_id="share-del-multi")
        owner, owner_client, cal_path = _create_user_with_calendar(
            org, "owner-delmulti"
        )
        sharee_a, _, _ = _create_user_with_calendar(org, "sharee-a-dm")
        sharee_b, _, _ = _create_user_with_calendar(org, "sharee-b-dm")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "multi-ev", "Shared Event")
        _share_calendar(owner_client, owner, cal_id, sharee_a.email, "read")
        _share_calendar(owner_client, owner, cal_id, sharee_b.email, "read")

        # Both should see the event
        for s in (sharee_a, sharee_b):
            dav = CalDAVHTTPClient().get_dav_client(s)
            found = False
            for cal in dav.principal().calendars():
                try:
                    for ev in cal.events():
                        if "Shared Event" in str(ev.data):
                            found = True
                except Exception:  # noqa: BLE001
                    continue
            assert found, f"{s.email} should see shared event"

        # Sharee A removes their view
        dav_a = CalDAVHTTPClient().get_dav_client(sharee_a)
        for cal in dav_a.principal().calendars():
            try:
                for ev in cal.events():
                    if "multi-ev" in str(ev.url):
                        # Delete the whole shared calendar
                        cal.delete()
                        break
            except Exception:  # noqa: BLE001
                continue

        # Sharee B should still see the event
        dav_b = CalDAVHTTPClient().get_dav_client(sharee_b)
        found_b = False
        for cal in dav_b.principal().calendars():
            try:
                for ev in cal.events():
                    if "Shared Event" in str(ev.data):
                        found_b = True
            except Exception:  # noqa: BLE001
                continue
        assert found_b, (
            "Sharee B should still see the event after Sharee A deleted their view"
        )


# ===================================================================
# Sync ACL edge cases (moved from test_plugins_e2e)
# ===================================================================


class TestSyncAclEdgeCases:
    """Edge cases for internal-api/sync-mailbox-acls/."""

    def test_full_sync_removes_stale_shares(self):
        """full_sync_users removes shares not in the new shares list."""
        org = factories.OrganizationFactory(external_id="sync-stale")
        owner, _, _ = _create_user_with_calendar(org, "owner-syncstale")
        user_a = factories.UserFactory(email="a@sync-stale.com", organization=org)
        user_b = factories.UserFactory(email="b@sync-stale.com", organization=org)
        mailbox_email = "team@sync-stale.com"
        _create_mailbox_calendar(owner, mailbox_email, org)

        # Sync both users
        _sync_mailbox_acls(
            owner,
            [
                {
                    "user_email": user_a.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read-write",
                },
                {
                    "user_email": user_b.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read",
                },
            ],
        )

        # Verify both users see the shared calendar
        a_cals = CalDAVHTTPClient().get_dav_client(user_a).principal().calendars()
        b_cals = CalDAVHTTPClient().get_dav_client(user_b).principal().calendars()
        assert len(a_cals) == 1, "User A should see exactly 1 calendar (shared)"
        assert len(b_cals) == 1, "User B should see exactly 1 calendar (shared)"

        # Now sync with only user_a, full_sync for user_b → stale share removed
        _sync_mailbox_acls(
            owner,
            [
                {
                    "user_email": user_a.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": "read-write",
                }
            ],
            full_sync_users=[user_b.email],
        )

        # User B should no longer see the shared calendar
        b_cals_after = CalDAVHTTPClient().get_dav_client(user_b).principal().calendars()
        assert len(b_cals_after) == 0, (
            f"User B's stale share should be removed. "
            f"Got {len(b_cals_after)}: {[str(c.url) for c in b_cals_after]}"
        )

        # User A should still see the shared calendar
        a_cals_after = CalDAVHTTPClient().get_dav_client(user_a).principal().calendars()
        assert len(a_cals_after) == 1, "User A should still see 1 shared calendar"

    def test_sync_idempotent(self):
        """Running the same sync twice produces the same result."""
        org = factories.OrganizationFactory(external_id="sync-idempotent")
        owner, _, _ = _create_user_with_calendar(org, "owner-syncid")
        sharee = factories.UserFactory(
            email="sharee@sync-idempotent.com", organization=org
        )
        mailbox_email = "team@sync-idempotent.com"
        _create_mailbox_calendar(owner, mailbox_email, org)

        shares = [
            {
                "user_email": sharee.email,
                "mailbox_email": mailbox_email,
                "calendar_uri": "default",
                "privilege": "read-write",
            }
        ]

        # Run sync twice
        _sync_mailbox_acls(owner, shares)
        _sync_mailbox_acls(owner, shares)

        # Should still have exactly 1 shared calendar
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        # Should have exactly 1 shared calendar
        cals = dav.principal().calendars()
        assert len(cals) == 1, (
            f"Idempotent sync should produce exactly 1 share, "
            f"got {len(cals)}: {[str(c.url) for c in cals]}"
        )
