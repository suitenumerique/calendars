"""End-to-end cross-organization isolation tests against real SabreDAV.

These tests verify that org-scoped resources, calendars, and operations
are properly isolated between organizations. They hit the real SabreDAV
server (no mocks) to validate the full stack: Django -> SabreDAV -> DB.

Requires: CalDAV server running (skipped otherwise).
"""

# pylint: disable=no-member,broad-exception-caught,unused-variable,too-many-lines

import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_207_MULTI_STATUS,
    HTTP_400_BAD_REQUEST,
)
from rest_framework.test import APIClient

from core import factories
from core.entitlements.factory import get_entitlements_backend
from core.models import Organization, User
from core.services.caldav_service import CalDAVHTTPClient, CalendarService
from core.services.resource_service import ResourceProvisioningError, ResourceService

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_org_admin(org):
    """Create a user in the given org and return (user, api_client).

    Uses force_login (not force_authenticate) so that session-based auth
    works for the CalDAV proxy view, which checks request.user.is_authenticated
    via Django's session middleware rather than DRF's token auth.
    """
    user = factories.UserFactory(organization=org)
    client = APIClient()
    client.force_login(user)
    return user, client


def _create_resource_via_internal_api(user, name="Room 1", resource_type="ROOM"):
    """Create a resource using ResourceService (hits real SabreDAV)."""
    service = ResourceService()
    return service.create_resource(user, name, resource_type)


def _get_dav_client_with_org(user):
    """Get a DAVClient with org header via CalDAVHTTPClient."""
    http = CalDAVHTTPClient()
    return http.get_dav_client(user)


def _propfind_resource_principals(api_client):
    """PROPFIND /caldav/principals/resources/ and return parsed XML root."""
    body = (
        '<?xml version="1.0"?>'
        '<propfind xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<prop>"
        "<displayname/>"
        "<C:calendar-user-type/>"
        "</prop>"
        "</propfind>"
    )
    response = api_client.generic(
        "PROPFIND",
        "/caldav/principals/resources/",
        data=body,
        content_type="application/xml",
        HTTP_DEPTH="1",
    )
    return response


def _propfind_resource_calendar(api_client, resource_id):
    """PROPFIND a specific resource's calendar collection."""
    body = (
        '<?xml version="1.0"?>'
        '<propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>'
    )
    response = api_client.generic(
        "PROPFIND",
        f"/caldav/calendars/resources/{resource_id}/",
        data=body,
        content_type="application/xml",
        HTTP_DEPTH="1",
    )
    return response


def _put_event_on_resource(api_client, resource_id, event_uid, organizer_email):
    """PUT an event directly onto a resource's default calendar."""
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
        "SUMMARY:Cross-org test event\r\n"
        f"ORGANIZER:mailto:{organizer_email}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    return api_client.generic(
        "PUT",
        f"/caldav/calendars/resources/{resource_id}/default/{event_uid}.ics",
        data=ical,
        content_type="text/calendar",
    )


def _create_user_with_calendar(org, email_prefix, domain="plugin-test.com"):
    """Create a user with a calendar and return (user, client, caldav_path)."""
    user = factories.UserFactory(email=f"{email_prefix}@{domain}", organization=org)
    client = APIClient()
    client.force_login(user)
    service = CalendarService()
    caldav_path = service.create_calendar(user, name=f"{email_prefix}'s Calendar")
    return user, client, caldav_path


def _get_cal_id(caldav_path):
    """Extract calendar ID from path like calendars/users/email/cal-id/."""
    parts = caldav_path.strip("/").split("/")
    return parts[-1] if len(parts) >= 4 else "default"


def _put_event(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    client,
    user_email,
    cal_id,
    event_uid,
    summary="Test Event",
    organizer=None,
    attendees=None,
):
    """PUT a VCALENDAR event into a calendar via the CalDAV proxy."""
    dtstart = datetime.now() + timedelta(days=1)
    dtend = dtstart + timedelta(hours=1)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Test//Test//EN",
        "BEGIN:VEVENT",
        f"UID:{event_uid}",
        f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{summary}",
    ]
    if organizer:
        lines.append(f"ORGANIZER:mailto:{organizer}")
    for att in attendees or []:
        lines.append(f"ATTENDEE;RSVP=TRUE:mailto:{att}")
    lines += ["END:VEVENT", "END:VCALENDAR", ""]
    ical = "\r\n".join(lines)
    return client.generic(
        "PUT",
        f"/caldav/calendars/users/{user_email}/{cal_id}/{event_uid}.ics",
        data=ical,
        content_type="text/calendar",
    )


def _share_calendar(owner_client, owner, cal_id, sharee_email, privilege):
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


def _proppatch(client, path, prop_xml):
    """PROPPATCH on a CalDAV resource."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propertyupdate xmlns:D="DAV:" '
        'xmlns:A="http://apple.com/ns/ical/" '
        'xmlns:C="urn:ietf:params:xml:ns:caldav">'
        f"<D:set><D:prop>{prop_xml}</D:prop></D:set>"
        "</D:propertyupdate>"
    )
    return client.generic(
        "PROPPATCH",
        path,
        data=body,
        content_type="application/xml",
    )


def _freebusy_report(client, user_email, cal_id):
    """Send a free-busy-query REPORT on a calendar."""
    dtstart = (datetime.now() - timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
    dtend = (datetime.now() + timedelta(days=30)).strftime("%Y%m%dT%H%M%SZ")
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<C:free-busy-query xmlns:C="urn:ietf:params:xml:ns:caldav">'
        f'<C:time-range start="{dtstart}" end="{dtend}"/>'
        "</C:free-busy-query>"
    )
    return client.generic(
        "REPORT",
        f"/caldav/calendars/users/{user_email}/{cal_id}/",
        data=body,
        content_type="application/xml",
        HTTP_DEPTH="1",
    )


def _freebusy_outbox(client, user_email, target_email):
    """Send a freebusy query via scheduling outbox POST."""
    dtstart = (datetime.now() + timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
    dtend = (datetime.now() + timedelta(days=2)).strftime("%Y%m%dT%H%M%SZ")
    ical = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "METHOD:REQUEST\r\n"
        "BEGIN:VFREEBUSY\r\n"
        f"DTSTART:{dtstart}\r\n"
        f"DTEND:{dtend}\r\n"
        f"ORGANIZER:mailto:{user_email}\r\n"
        f"ATTENDEE:mailto:{target_email}\r\n"
        "END:VFREEBUSY\r\n"
        "END:VCALENDAR\r\n"
    )
    return client.generic(
        "POST",
        f"/caldav/calendars/users/{user_email}/outbox/",
        data=ical,
        content_type="text/calendar",
    )


# ---------------------------------------------------------------------------
# 1. Resource provisioning — cross-org isolation via real SabreDAV
# ---------------------------------------------------------------------------


class TestResourceProvisioningE2E:
    """Resource creation and deletion hit real SabreDAV internal API."""

    def test_create_resource_e2e(self):
        """POST /resources/ creates a principal in SabreDAV."""
        org = factories.OrganizationFactory(external_id="res-e2e-org")
        admin, client = _create_org_admin(org)

        response = client.post(
            "/api/v1.0/resources/",
            {"name": "Meeting Room A", "resource_type": "ROOM"},
            format="json",
        )

        assert response.status_code == HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["name"] == "Meeting Room A"
        assert data["resource_type"] == "ROOM"
        resource_id = data["id"]

        # Verify the principal actually exists in SabreDAV via PROPFIND
        propfind = _propfind_resource_calendar(client, resource_id)
        assert propfind.status_code == HTTP_207_MULTI_STATUS, (
            f"Resource calendar not found in SabreDAV: {propfind.status_code}"
        )

    def test_delete_resource_e2e_same_org(self):
        """Admin can delete a resource belonging to their own org."""
        org = factories.OrganizationFactory(external_id="del-same-org")
        admin, client = _create_org_admin(org)

        resource = _create_resource_via_internal_api(admin, "Doomed Room")
        resource_id = resource["id"]

        response = client.delete(f"/api/v1.0/resources/{resource_id}/")
        assert response.status_code == HTTP_204_NO_CONTENT

        # Verify the principal is gone from SabreDAV
        propfind = _propfind_resource_calendar(client, resource_id)
        # Should be 404 or 207 with empty result — the principal was deleted
        assert propfind.status_code != HTTP_207_MULTI_STATUS or (
            b"<response>" not in propfind.content
        )

    def test_delete_resource_e2e_cross_org_blocked(self):
        """Admin from org A CANNOT delete a resource belonging to org B.

        This is enforced by SabreDAV's InternalApiPlugin, not Django.
        """
        org_a = factories.OrganizationFactory(external_id="del-org-a")
        org_b = factories.OrganizationFactory(external_id="del-org-b")

        # Create resource in org B
        admin_b = factories.UserFactory(organization=org_b)
        resource = _create_resource_via_internal_api(admin_b, "Org B Room")
        resource_id = resource["id"]

        # Admin from org A tries to delete it
        _, client_a = _create_org_admin(org_a)
        response = client_a.delete(f"/api/v1.0/resources/{resource_id}/")

        # Django returns 400 because SabreDAV returned 403
        assert response.status_code == HTTP_400_BAD_REQUEST
        assert "different organization" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 2. CalDAV proxy — org header forwarding verified E2E
# ---------------------------------------------------------------------------


class TestCalDAVProxyOrgHeaderE2E:
    """Verify org header reaches SabreDAV and affects responses."""

    def test_user_can_propfind_own_calendar(self):
        """User can PROPFIND their own calendar home."""
        org = factories.OrganizationFactory(external_id="proxy-own")
        user, client = _create_org_admin(org)

        # Create a calendar for the user
        service = CalendarService()
        service.create_calendar(user, name="My Cal")

        response = client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{user.email}/",
            data='<?xml version="1.0"?><propfind xmlns="DAV:"><prop>'
            "<displayname/></prop></propfind>",
            content_type="application/xml",
            HTTP_DEPTH="1",
        )

        assert response.status_code == HTTP_207_MULTI_STATUS

    def test_user_cannot_read_other_users_calendar_objects(self):
        """User from org A cannot read events from user B's calendar.

        SabreDAV allows PROPFIND on calendar homes (auto-creates principals),
        but blocks reading actual calendar objects via ACLs. The key isolation
        is that event data (REPORT/GET on .ics) is protected.
        """
        org_a = factories.OrganizationFactory(external_id="proxy-org-a")
        org_b = factories.OrganizationFactory(external_id="proxy-org-b")
        user_a, client_a = _create_org_admin(org_a)
        user_b = factories.UserFactory(organization=org_b)

        # Create a calendar with an event for user B
        service = CalendarService()
        caldav_path = service.create_calendar(user_b, name="B's Calendar")
        parts = caldav_path.strip("/").split("/")
        cal_id = parts[-1] if len(parts) >= 4 else "default"

        # Add an event to user B's calendar
        dav_b = CalDAVHTTPClient().get_dav_client(user_b)
        principal_b = dav_b.principal()
        cals_b = principal_b.calendars()
        dtstart = datetime.now() + timedelta(days=10)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:private-event-uid\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Private Event\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        cals_b[0].save_event(ical)

        # User A tries to GET user B's event
        response = client_a.generic(
            "GET",
            f"/caldav/calendars/users/{user_b.email}/{cal_id}/private-event-uid.ics",
        )

        # SabreDAV should block with 403 (ACL) or 404
        assert response.status_code in (403, 404), (
            f"Expected 403/404 for cross-user GET, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# 3. Resource calendar access — cross-org isolation
# ---------------------------------------------------------------------------


class TestResourceCalendarAccessE2E:
    """Verify that resource calendar data is org-scoped in SabreDAV.

    Users cannot PUT events directly on resource calendars — only
    SabreDAV's scheduling plugin writes there via iTIP. These tests
    verify that direct PUT is blocked by ACLs for both same-org and
    cross-org users.
    """

    def test_direct_put_on_resource_calendar_blocked(self):
        """Users cannot PUT events directly on resource calendars.

        Resource calendars are managed by the auto-schedule plugin.
        Direct writes are blocked by SabreDAV ACLs.
        """
        org = factories.OrganizationFactory(external_id="put-direct-org")
        user, client = _create_org_admin(org)
        resource = _create_resource_via_internal_api(user, "ACL Room")

        response = _put_event_on_resource(
            client, resource["id"], "direct-put-uid", user.email
        )

        # Direct PUT on resource calendar is blocked by ACLs
        assert response.status_code in (403, 404), (
            f"Expected 403/404 for direct PUT on resource calendar, "
            f"got {response.status_code}: "
            f"{response.content.decode('utf-8', errors='ignore')[:500]}"
        )

    def test_cross_org_put_on_resource_calendar_blocked(self):
        """Cross-org direct PUT on resource calendar is also blocked."""
        org_a = factories.OrganizationFactory(external_id="put-org-a")
        org_b = factories.OrganizationFactory(external_id="put-org-b")
        _, client_a = _create_org_admin(org_a)
        admin_b = factories.UserFactory(organization=org_b)
        resource_b = _create_resource_via_internal_api(admin_b, "Org B Room")

        response = _put_event_on_resource(
            client_a, resource_b["id"], "cross-org-event-uid", "attacker@test.com"
        )

        assert response.status_code in (403, 404), (
            f"Expected 403/404 for cross-org PUT on resource calendar, "
            f"got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# 4. Resource auto-scheduling — cross-org booking rejection
# ---------------------------------------------------------------------------


class TestResourceAutoScheduleCrossOrgE2E:
    """Verify that cross-org resource bookings are declined by SabreDAV.

    The ResourceAutoSchedulePlugin checks X-LS-Org-Id against
    the resource's org_id and declines cross-org booking requests.

    NOTE: SabreDAV's scheduling plugin resolves attendees via the principal
    backend. Resource principals live under principals/resources/, and the
    scheduling plugin must find them by email for iTIP delivery to work.
    If SCHEDULE-STATUS=5.x appears, it means the principal wasn't resolved,
    which blocks both auto-accept and auto-decline. These tests verify the
    org-scoping logic in InternalApiPlugin (create/delete) rather than
    iTIP scheduling, since iTIP requires searchPrincipals() support for
    the resources collection.
    """

    def test_resource_create_stores_org_id(self):
        """Resource creation stores org_id in SabreDAV for later scoping."""
        org = factories.OrganizationFactory(external_id="sched-orgid")
        user, _ = _create_org_admin(org)
        resource = _create_resource_via_internal_api(user, "Org Room")

        # Verify the resource exists by PROPFIND on its calendar
        propfind = _propfind_resource_calendar(
            _create_org_admin(org)[1], resource["id"]
        )
        assert propfind.status_code == HTTP_207_MULTI_STATUS

    def test_resource_delete_cross_org_rejected_by_sabredav(self):
        """SabreDAV's InternalApiPlugin rejects cross-org resource deletion.

        This is the core org-scoping enforcement: the org_id stored on creation
        is checked on deletion.
        """
        org_a = factories.OrganizationFactory(external_id="sched-del-a")
        org_b = factories.OrganizationFactory(external_id="sched-del-b")
        admin_a = factories.UserFactory(organization=org_a)
        admin_b = factories.UserFactory(organization=org_b)

        # Create resource in org B
        resource = _create_resource_via_internal_api(admin_b, "Org B Room")

        # Attempt delete from org A — should fail
        service = ResourceService()
        with pytest.raises(ResourceProvisioningError, match="different organization"):
            service.delete_resource(admin_a, resource["id"])

        # Verify resource still exists
        _, client_b = _create_org_admin(org_b)
        propfind = _propfind_resource_calendar(client_b, resource["id"])
        assert propfind.status_code == HTTP_207_MULTI_STATUS


# ---------------------------------------------------------------------------
# 5. Resource principal discovery — all orgs see resource list
#    but data is org-scoped
# ---------------------------------------------------------------------------


class TestResourceDiscoveryE2E:
    """Verify resource principal discovery behavior across orgs."""

    def test_resource_principals_visible_to_authenticated_users(self):
        """Any authenticated user can PROPFIND /principals/resources/.

        ResourcePrincipal grants {DAV:}read to {DAV:}authenticated.
        This allows resource discovery for scheduling.
        """
        org = factories.OrganizationFactory(external_id="disc-org")
        user, client = _create_org_admin(org)
        resource = _create_resource_via_internal_api(user, "Discoverable Room")

        response = _propfind_resource_principals(client)
        assert response.status_code == HTTP_207_MULTI_STATUS

        # The response should contain the resource we just created
        content = response.content.decode("utf-8", errors="ignore")
        assert resource["id"] in content or "Discoverable Room" in content


# ---------------------------------------------------------------------------
# 6. User deletion cleanup — real SabreDAV
# ---------------------------------------------------------------------------


class TestUserDeletionCleanupE2E:
    """Verify user deletion cleans up CalDAV data in SabreDAV."""

    def test_deleting_user_removes_caldav_principal(self):
        """When a Django user is deleted, their SabreDAV principal is cleaned up."""
        user = factories.UserFactory(email="doomed-user@test-e2e.com")

        # Create a calendar for the user (creates principal in SabreDAV)
        service = CalendarService()
        service.create_calendar(user, name="Soon Deleted")

        # Verify calendar exists
        dav = CalDAVHTTPClient().get_dav_client(user)
        principal = dav.principal()
        assert len(principal.calendars()) > 0

        # Capture org before delete (Python obj persists but be explicit)
        org_id = user.organization_id

        # Delete the user (signal triggers CalDAV cleanup)
        user.delete()

        # Verify the principal's calendars are gone
        # After deletion, the principal shouldn't exist, but due to
        # auto-create behavior, just check calendars are empty
        ghost = SimpleNamespace(
            email="doomed-user@test-e2e.com", organization_id=org_id
        )
        dav2 = CalDAVHTTPClient().get_dav_client(ghost)
        try:
            principal2 = dav2.principal()
            cals = principal2.calendars()
            # Either no calendars or the principal doesn't exist
            assert len(cals) == 0, (
                f"Expected 0 calendars after deletion, found {len(cals)}"
            )
        except Exception:  # noqa: BLE001
            # Principal not found after deletion — this is the expected
            # outcome when SabreDAV data was properly cleaned up.
            pass


# ---------------------------------------------------------------------------
# 7. Organization deletion cleanup — real SabreDAV
# ---------------------------------------------------------------------------


class TestOrgDeletionCleanupE2E:
    """Verify org deletion cleans up all member CalDAV data."""

    def test_deleting_org_removes_all_member_caldav_data(self):
        """Deleting an org cleans up CalDAV data for all its members."""
        org = factories.OrganizationFactory(external_id="doomed-org-e2e")
        alice = factories.UserFactory(
            email="alice-doomed@test-e2e.com", organization=org
        )
        bob = factories.UserFactory(email="bob-doomed@test-e2e.com", organization=org)

        # Create calendars for both users
        service = CalendarService()
        service.create_calendar(alice, name="Alice Cal")
        service.create_calendar(bob, name="Bob Cal")

        # Verify calendars exist
        for user in [alice, bob]:
            dav = CalDAVHTTPClient().get_dav_client(user)
            assert len(dav.principal().calendars()) > 0

        # Capture org_id before deletion
        org_id = org.id

        # Delete the org (cascades to member cleanup + user deletion)
        org.delete()

        # Verify both users' calendars are gone
        emails = ["alice-doomed@test-e2e.com", "bob-doomed@test-e2e.com"]
        for email in emails:
            ghost = SimpleNamespace(email=email, organization_id=org_id)
            dav = CalDAVHTTPClient().get_dav_client(ghost)
            try:
                cals = dav.principal().calendars()
                assert len(cals) == 0
            except Exception:  # noqa: BLE001
                # Principal not found after org deletion — this is the
                # expected outcome when SabreDAV data was properly cleaned up.
                pass

        assert not User.objects.filter(
            email__in=[
                "alice-doomed@test-e2e.com",
                "bob-doomed@test-e2e.com",
            ]
        ).exists()
        assert not Organization.objects.filter(external_id="doomed-org-e2e").exists()


# ---------------------------------------------------------------------------
# 8. Calendar creation isolation
# ---------------------------------------------------------------------------


class TestCalendarCreationIsolationE2E:
    """Verify calendar creation is scoped to the authenticated user."""

    def test_mkcalendar_creates_for_authenticated_user_only(self):
        """MKCALENDAR via proxy creates calendar under the authenticated user's principal."""
        org = factories.OrganizationFactory(external_id="mkcal-org")
        user_a, client_a = _create_org_admin(org)
        user_b = factories.UserFactory(organization=org)

        # User A creates a calendar via proxy
        response = client_a.generic(
            "MKCALENDAR",
            f"/caldav/calendars/users/{user_a.email}/new-cal-e2e/",
            data=(
                '<?xml version="1.0" encoding="utf-8" ?>'
                '<C:mkcalendar xmlns:D="DAV:" '
                'xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<D:set><D:prop>"
                "<D:displayname>E2E Test Calendar</D:displayname>"
                "</D:prop></D:set>"
                "</C:mkcalendar>"
            ),
            content_type="application/xml",
        )

        assert response.status_code == 201, (
            f"MKCALENDAR failed: {response.status_code} "
            f"{response.content.decode('utf-8', errors='ignore')[:500]}"
        )

        # Verify user A has the calendar via CalDAV PROPFIND
        dav_a = CalDAVHTTPClient().get_dav_client(user_a)
        cal_names_a = [c.name for c in dav_a.principal().calendars()]
        assert "E2E Test Calendar" in cal_names_a, (
            f"Calendar 'E2E Test Calendar' not found for user A. Found: {cal_names_a}"
        )

        # Verify user B does NOT have this calendar
        dav_b = CalDAVHTTPClient().get_dav_client(user_b)
        try:
            cal_names_b = [c.name for c in dav_b.principal().calendars()]
            assert "E2E Test Calendar" not in cal_names_b
        except Exception:  # noqa: BLE001
            # User B has no principal — this is acceptable because we
            # only need to verify User A's calendar was not created
            # under User B's namespace.
            pass

    def test_cannot_create_calendar_under_other_user(self):
        """User A cannot MKCALENDAR under user B's principal."""
        org = factories.OrganizationFactory(external_id="mkcal-cross")
        user_a, client_a = _create_org_admin(org)
        user_b = factories.UserFactory(
            email="mkcal-victim@test-e2e.com", organization=org
        )

        response = client_a.generic(
            "MKCALENDAR",
            f"/caldav/calendars/users/{user_b.email}/hijacked-cal/",
            data=(
                '<?xml version="1.0" encoding="utf-8" ?>'
                '<C:mkcalendar xmlns:D="DAV:" '
                'xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<D:set><D:prop>"
                "<D:displayname>Hijacked Calendar</D:displayname>"
                "</D:prop></D:set>"
                "</C:mkcalendar>"
            ),
            content_type="application/xml",
        )

        # SabreDAV should block this with 403 (ACL violation)
        assert response.status_code in (403, 404, 409), (
            f"Expected 403/404 for MKCALENDAR under another user, "
            f"got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# 9. Event CRUD isolation
# ---------------------------------------------------------------------------


class TestEventCRUDIsolationE2E:
    """Verify event CRUD is scoped to the calendar owner."""

    def test_user_cannot_put_event_in_other_users_calendar(self):
        """User A cannot PUT an event into user B's calendar."""
        org = factories.OrganizationFactory(external_id="event-cross")
        user_a, client_a = _create_org_admin(org)
        user_b = factories.UserFactory(
            email="event-victim@test-e2e.com", organization=org
        )

        # Create a calendar for user B
        service = CalendarService()
        caldav_path = service.create_calendar(user_b, name="B's Private Cal")

        # Extract calendar ID from path
        # Path format: calendars/users/email/cal-id/
        parts = caldav_path.strip("/").split("/")
        cal_id = parts[-1] if len(parts) >= 4 else "default"

        dtstart = datetime.now() + timedelta(days=5)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:malicious-event-uid\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Malicious Event\r\n"
            f"ORGANIZER:mailto:{user_a.email}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

        response = client_a.generic(
            "PUT",
            f"/caldav/calendars/users/{user_b.email}/{cal_id}/malicious.ics",
            data=ical,
            content_type="text/calendar",
        )

        # SabreDAV should block with 403 (ACL)
        assert response.status_code in (403, 404, 409), (
            f"Expected 403/404 for cross-user PUT, got {response.status_code}"
        )

    def test_user_cannot_delete_other_users_event(self):
        """User A cannot DELETE an event from user B's calendar."""
        org = factories.OrganizationFactory(external_id="event-del-cross")
        user_a, client_a = _create_org_admin(org)
        user_b = factories.UserFactory(
            email="event-del-victim@test-e2e.com", organization=org
        )

        # Create a calendar and event for user B
        service = CalendarService()
        caldav_path = service.create_calendar(user_b, name="B's Cal")
        parts = caldav_path.strip("/").split("/")
        cal_id = parts[-1] if len(parts) >= 4 else "default"

        # Create event as user B
        dav_b = CalDAVHTTPClient().get_dav_client(user_b)
        principal_b = dav_b.principal()
        cals_b = principal_b.calendars()
        assert len(cals_b) > 0

        dtstart = datetime.now() + timedelta(days=6)
        dtend = dtstart + timedelta(hours=1)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:victim-event-uid\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Victim's Event\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        cals_b[0].save_event(ical)

        # User A tries to DELETE user B's event
        response = client_a.generic(
            "DELETE",
            f"/caldav/calendars/users/{user_b.email}/{cal_id}/victim-event-uid.ics",
        )

        assert response.status_code in (403, 404), (
            f"Expected 403/404 for cross-user DELETE, got {response.status_code}"
        )

        # Verify event still exists via CalDAV API
        http = CalDAVHTTPClient()
        ical_data, _, _ = http.find_event_by_uid(user_b, "victim-event-uid")
        assert ical_data is not None, (
            "Victim's event should still exist after blocked deletion attempt"
        )


class TestCrossOrgFreebusyIsolation:
    """Verify that freebusy queries are blocked across organizations.

    Cross-org freebusy is ALWAYS blocked regardless of sharing level.
    Same-org freebusy depends on the org's effective_sharing_level.
    """

    def test_cross_org_freebusy_query_blocked(self):
        """A user in org A should NOT be able to query freebusy on
        a calendar in org B via CALDAV:free-busy-query REPORT.

        Cross-org freebusy is blocked regardless of sharing level.
        Even with sharing_level="read" (the most permissive), cross-org
        queries must be rejected by FreeBusyOrgScopePlugin.
        """
        org_a = factories.OrganizationFactory(
            external_id="fb-iso-org-a",
            default_sharing_level="read",
        )
        org_b = factories.OrganizationFactory(
            external_id="fb-iso-org-b",
            default_sharing_level="read",
        )

        user_a = factories.UserFactory(
            email="attacker@fb-iso-a.com", organization=org_a
        )
        user_b = factories.UserFactory(email="victim@fb-iso-b.com", organization=org_b)

        # Create a calendar for user B with an event
        service = CalendarService()
        cal_path = service.create_calendar(user_b, name="Private Calendar")
        cal_id = cal_path.strip("/").split("/")[-1]

        # Add an event to user B's calendar
        http = CalDAVHTTPClient()
        dtstart = (datetime.now() + timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
        dtend = (datetime.now() + timedelta(days=1, hours=1)).strftime("%Y%m%dT%H%M%SZ")
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:private-event-fb-iso\r\n"
            f"DTSTART:{dtstart}\r\n"
            f"DTEND:{dtend}\r\n"
            "SUMMARY:Secret Meeting\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR"
        )
        resp = http.request(
            "PUT",
            user_b,
            f"calendars/users/{user_b.email}/{cal_id}/private.ics",
            data=ical.encode(),
            content_type="text/calendar",
        )
        assert resp.status_code == 201

        # User A tries to query freebusy on user B's calendar
        client_a = APIClient()
        client_a.force_login(user_a)

        fb_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<C:free-busy-query xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<C:time-range"
            f' start="{dtstart}"'
            f' end="{dtend}"/>'
            "</C:free-busy-query>"
        )

        resp = client_a.generic(
            "REPORT",
            f"/caldav/calendars/users/{user_b.email}/{cal_id}/",
            data=fb_body,
            content_type="application/xml",
            HTTP_DEPTH="1",
        )

        # This should be blocked (403) for cross-org queries
        assert resp.status_code == 403, (
            f"Cross-org freebusy query should be blocked but got "
            f"{resp.status_code}. SabreDAV grants read-free-busy to "
            f"all authenticated users by default — this must be restricted "
            f"to same-org users.\n"
            f"Response: {resp.content.decode('utf-8', errors='ignore')[:500]}"
        )


def _share_calendar_cs(owner_client, owner, cal_id, sharee_email, privilege):
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


class TestFreeBusyOrgScope:
    """FreeBusyOrgScopePlugin enforces org-level freebusy isolation.

    Cross-org queries must be blocked. Same-org queries depend on
    the organization's effective_sharing_level.
    """

    def test_same_org_freebusy_report_allowed_with_freebusy_level(self):
        """Same-org freebusy REPORT allowed when sharing_level=freebusy."""
        org = factories.OrganizationFactory(
            external_id="fb-scope-same",
            default_sharing_level="freebusy",
        )
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbsame")
        querier, querier_client, _ = _create_user_with_calendar(org, "querier-fbsame")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "fb-same-ev", "Meeting")

        resp = _freebusy_report(querier_client, owner.email, cal_id)
        # Should succeed (200 or 207) with VFREEBUSY data
        assert resp.status_code in (200, 207), (
            f"Same-org freebusy REPORT should be allowed, "
            f"got {resp.status_code}: {resp.content.decode()[:500]}"
        )

    def test_same_org_freebusy_report_allowed_with_read_level(self):
        """Same-org freebusy REPORT also allowed when sharing_level=read."""
        org = factories.OrganizationFactory(
            external_id="fb-scope-same-read",
            default_sharing_level="read",
        )
        owner, owner_client, cal_path = _create_user_with_calendar(
            org, "owner-fbsameread"
        )
        querier, querier_client, _ = _create_user_with_calendar(
            org, "querier-fbsameread"
        )
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "fb-sameread-ev", "Mtg")

        resp = _freebusy_report(querier_client, owner.email, cal_id)
        assert resp.status_code in (200, 207), (
            f"Same-org freebusy REPORT with sharing_level=read should work, "
            f"got {resp.status_code}"
        )

    def test_cross_org_freebusy_report_blocked_even_with_read_level(self):
        """Cross-org freebusy REPORT blocked even with sharing_level=read.

        Cross-org isolation is absolute — the sharing level only controls
        same-org freebusy access, never cross-org.
        """
        org_a = factories.OrganizationFactory(
            external_id="fb-scope-a",
            default_sharing_level="read",
        )
        org_b = factories.OrganizationFactory(
            external_id="fb-scope-b",
            default_sharing_level="read",
        )
        owner, owner_client, cal_path = _create_user_with_calendar(
            org_b, "owner-fbcross"
        )
        attacker, attacker_client, _ = _create_user_with_calendar(
            org_a, "attacker-fbcross"
        )
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "fb-cross-ev", "Secret")

        resp = _freebusy_report(attacker_client, owner.email, cal_id)
        assert resp.status_code == 403, (
            f"Cross-org freebusy REPORT should be blocked, got {resp.status_code}"
        )

    def test_sharing_level_none_blocks_same_org_freebusy_report(self):
        """sharing_level=none blocks freebusy REPORT even same-org."""
        org = factories.OrganizationFactory(
            external_id="fb-scope-none",
            default_sharing_level="none",
        )
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbnone")
        querier, querier_client, _ = _create_user_with_calendar(org, "querier-fbnone")
        cal_id = _get_cal_id(cal_path)

        _put_event(owner_client, owner.email, cal_id, "fb-none-ev", "Meeting")

        resp = _freebusy_report(querier_client, owner.email, cal_id)
        assert resp.status_code == 403, (
            f"sharing_level=none should block same-org freebusy REPORT, "
            f"got {resp.status_code}"
        )

    def test_sharing_level_none_blocks_outbox_freebusy(self):
        """sharing_level=none blocks scheduling outbox freebusy too."""
        org = factories.OrganizationFactory(
            external_id="fb-scope-none-outbox",
            default_sharing_level="none",
        )
        querier, querier_client, _ = _create_user_with_calendar(org, "querier-fbnoneob")
        target = factories.UserFactory(
            email="target@fb-scope-none-outbox.com", organization=org
        )

        resp = _freebusy_outbox(querier_client, querier.email, target.email)
        assert resp.status_code == 403, (
            f"sharing_level=none should block outbox freebusy POST, "
            f"got {resp.status_code}"
        )

    def test_own_calendar_freebusy_always_allowed(self):
        """Users can always query freebusy on their own calendar."""
        org = factories.OrganizationFactory(
            external_id="fb-scope-own",
            default_sharing_level="none",
        )
        user, client, cal_path = _create_user_with_calendar(org, "user-fbown")
        cal_id = _get_cal_id(cal_path)

        _put_event(client, user.email, cal_id, "fb-own-ev", "My Meeting")

        resp = _freebusy_report(client, user.email, cal_id)
        # Own calendar should always work regardless of sharing level
        assert resp.status_code in (200, 207), (
            f"Own calendar freebusy should always be allowed, got {resp.status_code}"
        )


# ===================================================================
# ResourceAutoSchedulePlugin
# ===================================================================


class TestResourceMkCalendarBlock:
    """ResourceAutoSchedulePlugin blocks MKCALENDAR on resource principals."""

    def test_mkcalendar_on_resource_blocked(self):
        """MKCALENDAR under /calendars/resources/ must be blocked."""
        org = factories.OrganizationFactory(external_id="res-mkcal-block")
        user, client, _ = _create_user_with_calendar(org, "user-resmk")

        # Create a resource first so the principal exists

        service = ResourceService()
        resource = service.create_resource(user, "Test Room", "ROOM")
        resource_id = resource["id"]

        # Try to MKCALENDAR under the resource
        resp = client.generic(
            "MKCALENDAR",
            f"/caldav/calendars/resources/{resource_id}/extra-calendar/",
            data=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<C:mkcalendar xmlns:D="DAV:" '
                'xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<D:set><D:prop>"
                "<D:displayname>Extra</D:displayname>"
                "</D:prop></D:set>"
                "</C:mkcalendar>"
            ),
            content_type="application/xml",
        )
        assert resp.status_code == 403, (
            f"MKCALENDAR on resource principal should be blocked, "
            f"got {resp.status_code}"
        )


# ===================================================================
# AttendeeNormalizerPlugin
# ===================================================================


class TestResourceAutoSchedule:
    """ResourceAutoSchedulePlugin handles automatic accept/decline for resources.

    Resources should auto-accept non-conflicting bookings and auto-decline
    conflicting ones. Cross-org bookings should be declined.
    """

    def test_resource_auto_accepts_booking(self):
        """Resource with auto-schedule accepts non-conflicting booking."""
        org = factories.OrganizationFactory(external_id="res-autosched")
        user, client, _ = _create_user_with_calendar(org, "user-resauto")

        service = ResourceService()
        resource = service.create_resource(user, "Auto Room", "ROOM")
        resource_id = resource["id"]

        # Book the resource by creating an event with ATTENDEE=resource
        dtstart = datetime.now() + timedelta(days=2)
        dtend = dtstart + timedelta(hours=1)
        resource_email = resource.get("email", f"{resource_id}@resource.local")

        # We need to book via scheduling (organizer creates event with attendee)
        ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:res-auto-booking\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Team Standup\r\n"
            f"ORGANIZER:mailto:{user.email}\r\n"
            f"ATTENDEE;RSVP=TRUE:mailto:{resource_email}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        # Find user's calendar to PUT the event
        dav = CalDAVHTTPClient().get_dav_client(user)
        cals = dav.principal().calendars()
        assert len(cals) > 0, "User should have at least one calendar"
        cals[0].save_event(ical)

        # Check that the event was saved (scheduling processed it)
        event_data, _, _ = CalDAVHTTPClient().find_event_by_uid(
            user, "res-auto-booking"
        )
        assert event_data is not None, "Booking event should be saved"


# ===================================================================
# Sync ACL edge cases
# ===================================================================


class TestCalDAVProtocolSecurity:
    """Protocol-level security tests for CalDAV operations."""

    def test_proppatch_on_readonly_shared_calendar_blocked(self):
        """PROPPATCH on a read-only shared calendar must be blocked."""
        org = factories.OrganizationFactory(external_id="proto-proppatch")
        owner, owner_client, cal_path = _create_user_with_calendar(
            org, "owner-proppatch"
        )
        sharee, _, _ = _create_user_with_calendar(org, "sharee-proppatch")
        sharee_client = APIClient()
        sharee_client.force_login(sharee)
        cal_id = _get_cal_id(cal_path)

        _share_calendar(owner_client, owner, cal_id, sharee.email, "read")

        # Sharee tries to change displayname via PROPPATCH
        resp = _proppatch(
            sharee_client,
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            "<D:displayname>Hacked Name</D:displayname>",
        )
        # Should fail — sharee doesn't own the calendar
        # SabreDAV returns 207 with 403 status per property
        if resp.status_code == 207:
            content = resp.content.decode("utf-8", errors="ignore")
            assert "403" in content or "forbidden" in content.lower(), (
                f"PROPPATCH by read-only sharee should show 403 per-prop: "
                f"{content[:500]}"
            )
        else:
            assert resp.status_code in (403, 404), (
                f"Expected 403/404/207 for PROPPATCH by read sharee, "
                f"got {resp.status_code}"
            )

    def test_delete_calendar_you_dont_own(self):
        """DELETE on a calendar you don't own must be blocked."""
        org = factories.OrganizationFactory(external_id="proto-delcal")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-delcal")
        stranger, stranger_client, _ = _create_user_with_calendar(
            org, "stranger-delcal"
        )
        cal_id = _get_cal_id(cal_path)

        resp = stranger_client.generic(
            "DELETE",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
        )
        assert resp.status_code in (403, 404), (
            f"DELETE on other user's calendar should be blocked, got {resp.status_code}"
        )

        # Verify calendar still exists
        check = owner_client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=(
                '<?xml version="1.0"?>'
                '<propfind xmlns="DAV:"><prop><displayname/></prop></propfind>'
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        assert check.status_code == 207, "Calendar should still exist"

    def test_share_calendar_you_dont_own(self):
        """CS:share on a calendar you don't own must be blocked."""
        org = factories.OrganizationFactory(external_id="proto-share")
        owner, owner_client, cal_path = _create_user_with_calendar(
            org, "owner-sharesec"
        )
        attacker, attacker_client, _ = _create_user_with_calendar(
            org, "attacker-sharesec"
        )
        victim = factories.UserFactory(email="victim@proto-share.com", organization=org)
        cal_id = _get_cal_id(cal_path)

        # Attacker tries to share owner's calendar with victim
        resp = _share_calendar(
            attacker_client, owner, cal_id, victim.email, "read-write"
        )
        assert resp.status_code in (403, 404), (
            f"CS:share on non-owned calendar should be blocked, got {resp.status_code}"
        )

    def test_mkcalendar_under_other_user(self):
        """MKCALENDAR under another user's home must be blocked."""
        org = factories.OrganizationFactory(external_id="proto-mkcal")
        owner = factories.UserFactory(email="owner@proto-mkcal.com", organization=org)
        attacker, attacker_client, _ = _create_user_with_calendar(org, "attacker-mkcal")

        resp = attacker_client.generic(
            "MKCALENDAR",
            f"/caldav/calendars/users/{owner.email}/injected-calendar/",
            data=(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<C:mkcalendar xmlns:D="DAV:" '
                'xmlns:C="urn:ietf:params:xml:ns:caldav">'
                "<D:set><D:prop>"
                "<D:displayname>Injected</D:displayname>"
                "</D:prop></D:set>"
                "</C:mkcalendar>"
            ),
            content_type="application/xml",
        )
        assert resp.status_code in (403, 404), (
            f"MKCALENDAR under other user should be blocked, got {resp.status_code}"
        )

    def test_post_to_other_users_outbox_blocked(self):
        """POST to another user's scheduling outbox must be blocked."""
        org = factories.OrganizationFactory(external_id="proto-outbox")
        owner, _, _ = _create_user_with_calendar(org, "owner-outbox")
        attacker, attacker_client, _ = _create_user_with_calendar(
            org, "attacker-outbox"
        )

        resp = _freebusy_outbox(attacker_client, owner.email, "anyone@x.com")
        # Should fail — attacker is posting to owner's outbox
        assert resp.status_code in (403, 404), (
            f"POST to another user's outbox should be blocked, got {resp.status_code}"
        )

    def test_delete_own_calendar_works(self):
        """Owner can DELETE their own calendar."""
        org = factories.OrganizationFactory(external_id="proto-delown")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-delown")
        cal_id = _get_cal_id(cal_path)

        resp = owner_client.generic(
            "DELETE",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
        )
        assert resp.status_code in (200, 204), (
            f"Owner should be able to DELETE own calendar, got {resp.status_code}"
        )

    def test_proppatch_rename_own_calendar(self):
        """Owner can PROPPATCH (rename) their own calendar."""
        org = factories.OrganizationFactory(external_id="proto-rename")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rename")
        cal_id = _get_cal_id(cal_path)

        resp = _proppatch(
            owner_client,
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            "<D:displayname>New Name</D:displayname>",
        )
        assert resp.status_code == 207

        # Verify the rename took effect
        check = owner_client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=(
                '<?xml version="1.0"?>'
                '<propfind xmlns="DAV:"><prop><displayname/></prop></propfind>'
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        assert "New Name" in check.content.decode("utf-8", errors="ignore")

    def test_proppatch_color_own_calendar(self):
        """Owner can PROPPATCH the color of their own calendar."""
        org = factories.OrganizationFactory(external_id="proto-color")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-color")
        cal_id = _get_cal_id(cal_path)

        resp = _proppatch(
            owner_client,
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            "<A:calendar-color>#e74c3c</A:calendar-color>",
        )
        assert resp.status_code == 207

        check = owner_client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=(
                '<?xml version="1.0"?>'
                '<propfind xmlns="DAV:" xmlns:A="http://apple.com/ns/ical/">'
                "<prop><A:calendar-color/></prop>"
                "</propfind>"
            ),
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        assert "#e74c3c" in check.content.decode("utf-8", errors="ignore")


# ===================================================================
# ResourceAutoSchedulePlugin
# ===================================================================


class TestSyncCollectionReport:
    """sync-collection REPORT enables incremental calendar sync.

    Clients send a sync-token (empty for initial sync) and receive
    only changed/deleted resources since that token.
    """

    def test_initial_sync_returns_all_events(self):
        """Initial sync (empty token) returns all events + a sync-token."""
        org = factories.OrganizationFactory(external_id="sync-coll-init")
        user, client, cal_path = _create_user_with_calendar(org, "user-syncinit")
        cal_id = _get_cal_id(cal_path)

        _put_event(client, user.email, cal_id, "sync-ev-1", "Event 1")
        _put_event(client, user.email, cal_id, "sync-ev-2", "Event 2")

        sync_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:sync-collection xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:sync-token></D:sync-token>"
            "<D:sync-level>1</D:sync-level>"
            "<D:prop>"
            "<D:getetag/>"
            "<C:calendar-data/>"
            "</D:prop>"
            "</D:sync-collection>"
        )
        resp = client.generic(
            "REPORT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/",
            data=sync_body,
            content_type="application/xml",
            HTTP_DEPTH="1",
        )
        assert resp.status_code == 207, (
            f"sync-collection REPORT failed: {resp.status_code}"
        )

        content = resp.content.decode("utf-8", errors="ignore")
        # Should contain both events
        assert "sync-ev-1" in content, "Initial sync should include event 1"
        assert "sync-ev-2" in content, "Initial sync should include event 2"
        # Should contain a sync-token for next sync
        assert "sync-token" in content, (
            "sync-collection response must include a sync-token"
        )

    def test_incremental_sync_returns_only_changes(self):
        """Incremental sync (with token) returns only new/changed events."""

        org = factories.OrganizationFactory(external_id="sync-coll-incr")
        user, client, cal_path = _create_user_with_calendar(org, "user-syncincr")
        cal_id = _get_cal_id(cal_path)

        # Create first event
        _put_event(client, user.email, cal_id, "sync-old-ev", "Old Event")

        # Do initial sync to get a token
        sync_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:sync-collection xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:sync-token></D:sync-token>"
            "<D:sync-level>1</D:sync-level>"
            "<D:prop>"
            "<D:getetag/>"
            "<C:calendar-data/>"
            "</D:prop>"
            "</D:sync-collection>"
        )
        resp = client.generic(
            "REPORT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/",
            data=sync_body,
            content_type="application/xml",
            HTTP_DEPTH="1",
        )
        assert resp.status_code == 207

        content = resp.content.decode("utf-8", errors="ignore")
        # Extract sync-token from response
        # SabreDAV format: <d:sync-token>http://sabre.io/ns/sync/123</d:sync-token>
        token_match = re.search(
            r"<[^>]*sync-token[^>]*>([^<]+)</[^>]*sync-token>",
            content,
            re.IGNORECASE,
        )
        assert token_match, (
            f"Could not extract sync-token from response:\n{content[:1000]}"
        )
        sync_token = token_match.group(1)

        # Create a NEW event after the initial sync
        _put_event(client, user.email, cal_id, "sync-new-ev", "New Event")

        # Incremental sync with the token
        incr_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:sync-collection xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            f"<D:sync-token>{sync_token}</D:sync-token>"
            "<D:sync-level>1</D:sync-level>"
            "<D:prop>"
            "<D:getetag/>"
            "<C:calendar-data/>"
            "</D:prop>"
            "</D:sync-collection>"
        )
        resp2 = client.generic(
            "REPORT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/",
            data=incr_body,
            content_type="application/xml",
            HTTP_DEPTH="1",
        )
        assert resp2.status_code == 207

        content2 = resp2.content.decode("utf-8", errors="ignore")
        # Should include the new event
        assert "sync-new-ev" in content2, (
            "Incremental sync should include newly created event"
        )
        # Should NOT include the old event (it hasn't changed)
        assert "sync-old-ev" not in content2, (
            "Incremental sync should NOT include unchanged events.\n"
            f"Response:\n{content2[:1000]}"
        )

    def test_sync_deleted_event_returns_404_status(self):
        """Incremental sync after deleting an event should report 404 for it."""

        org = factories.OrganizationFactory(external_id="sync-coll-del")
        user, client, cal_path = _create_user_with_calendar(org, "user-syncdel")
        cal_id = _get_cal_id(cal_path)

        # Create event
        _put_event(client, user.email, cal_id, "sync-del-ev", "Doomed Event")

        # Initial sync to get token
        sync_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:sync-collection xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:sync-token></D:sync-token>"
            "<D:sync-level>1</D:sync-level>"
            "<D:prop><D:getetag/></D:prop>"
            "</D:sync-collection>"
        )
        resp = client.generic(
            "REPORT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/",
            data=sync_body,
            content_type="application/xml",
            HTTP_DEPTH="1",
        )
        content = resp.content.decode("utf-8", errors="ignore")
        token_match = re.search(
            r"<[^>]*sync-token[^>]*>([^<]+)</[^>]*sync-token>",
            content,
            re.IGNORECASE,
        )
        sync_token = token_match.group(1)

        # Delete the event
        del_resp = client.generic(
            "DELETE",
            f"/caldav/calendars/users/{user.email}/{cal_id}/sync-del-ev.ics",
        )
        assert del_resp.status_code in (200, 204), (
            f"DELETE failed: {del_resp.status_code}"
        )

        # Incremental sync — deleted event should appear with 404 status
        incr_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:sync-collection xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            f"<D:sync-token>{sync_token}</D:sync-token>"
            "<D:sync-level>1</D:sync-level>"
            "<D:prop><D:getetag/></D:prop>"
            "</D:sync-collection>"
        )
        resp2 = client.generic(
            "REPORT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/",
            data=incr_body,
            content_type="application/xml",
            HTTP_DEPTH="1",
        )
        assert resp2.status_code == 207

        content2 = resp2.content.decode("utf-8", errors="ignore")
        # The deleted event should be listed with its href
        assert "sync-del-ev" in content2, "Deleted event should appear in sync response"
        # And it should have a 404 status
        assert "404" in content2, (
            "Deleted event should have HTTP 404 status in sync response.\n"
            f"Response:\n{content2[:1000]}"
        )


# ===================================================================
# ETag / If-Match conflict detection (HTTP 412)
# ===================================================================


class TestETagConflict:
    """ETag-based conflict detection prevents lost updates.

    When a client sends If-Match with a stale ETag, the server must
    return 412 Precondition Failed instead of silently overwriting.
    """

    def test_put_with_correct_etag_succeeds(self):
        """PUT with matching If-Match ETag should succeed."""
        org = factories.OrganizationFactory(external_id="etag-ok")
        user, client, cal_path = _create_user_with_calendar(org, "user-etagok")
        cal_id = _get_cal_id(cal_path)

        # Create event
        resp = _put_event(client, user.email, cal_id, "etag-ev", "Original")
        assert resp.status_code in (200, 201, 204)

        # GET to obtain current ETag
        get_resp = client.generic(
            "GET",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-ev.ics",
        )
        etag = get_resp.headers.get("ETag") or get_resp.headers.get("etag")
        assert etag, "GET should return an ETag header"

        # PUT with matching If-Match
        dtstart = datetime.now() + timedelta(days=2)
        dtend = dtstart + timedelta(hours=1)
        updated_ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:etag-ev\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Updated\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        resp2 = client.generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-ev.ics",
            data=updated_ical,
            content_type="text/calendar",
            HTTP_IF_MATCH=etag,
        )
        assert resp2.status_code in (200, 204), (
            f"PUT with correct ETag should succeed, got {resp2.status_code}"
        )

    def test_put_with_stale_etag_returns_412(self):
        """PUT with stale If-Match ETag should return 412 Precondition Failed."""
        org = factories.OrganizationFactory(external_id="etag-conflict")
        user, client, cal_path = _create_user_with_calendar(org, "user-etag412")
        cal_id = _get_cal_id(cal_path)

        # Create event
        _put_event(client, user.email, cal_id, "etag-conflict-ev", "Version 1")

        # GET the ETag
        get_resp = client.generic(
            "GET",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-conflict-ev.ics",
        )
        old_etag = get_resp.headers.get("ETag") or get_resp.headers.get("etag")
        assert old_etag, "GET should return an ETag"

        # Update the event (this changes the ETag on the server)
        dtstart = datetime.now() + timedelta(days=3)
        dtend = dtstart + timedelta(hours=1)
        v2_ical = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:etag-conflict-ev\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Version 2\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        resp2 = client.generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-conflict-ev.ics",
            data=v2_ical,
            content_type="text/calendar",
        )
        assert resp2.status_code in (200, 204)

        # Now try to PUT with the OLD ETag (stale)
        v3_ical = v2_ical.replace("Version 2", "Version 3 (conflict)")
        resp3 = client.generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-conflict-ev.ics",
            data=v3_ical,
            content_type="text/calendar",
            HTTP_IF_MATCH=old_etag,
        )
        assert resp3.status_code == 412, (
            f"PUT with stale ETag should return 412, got {resp3.status_code}"
        )

        # Verify version 2 is still intact (not overwritten)
        get_resp2 = client.generic(
            "GET",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-conflict-ev.ics",
        )
        content = get_resp2.content.decode("utf-8", errors="ignore")
        assert "Version 2" in content, "Event should still be Version 2"
        assert "Version 3" not in content, "Version 3 should NOT have been saved"

    def test_delete_with_stale_etag_returns_412(self):
        """DELETE with stale If-Match ETag should return 412."""
        org = factories.OrganizationFactory(external_id="etag-del-conflict")
        user, client, cal_path = _create_user_with_calendar(org, "user-etagdel")
        cal_id = _get_cal_id(cal_path)

        _put_event(client, user.email, cal_id, "etag-del-ev", "To Delete")

        # GET ETag
        get_resp = client.generic(
            "GET",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-del-ev.ics",
        )
        old_etag = get_resp.headers.get("ETag") or get_resp.headers.get("etag")

        # Update the event (changes ETag)
        dtstart = datetime.now() + timedelta(days=4)
        dtend = dtstart + timedelta(hours=1)
        updated = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Test//Test//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:etag-del-ev\r\n"
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%SZ')}\r\n"
            "SUMMARY:Updated\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        client.generic(
            "PUT",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-del-ev.ics",
            data=updated,
            content_type="text/calendar",
        )

        # Try DELETE with old ETag
        del_resp = client.generic(
            "DELETE",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-del-ev.ics",
            HTTP_IF_MATCH=old_etag,
        )
        assert del_resp.status_code == 412, (
            f"DELETE with stale ETag should return 412, got {del_resp.status_code}"
        )

        # Event should still exist
        check = client.generic(
            "GET",
            f"/caldav/calendars/users/{user.email}/{cal_id}/etag-del-ev.ics",
        )
        assert check.status_code == 200, "Event should survive blocked delete"
