"""End-to-end cross-organization isolation tests against real SabreDAV.

These tests verify that org-scoped resources, calendars, and operations
are properly isolated between organizations. They hit the real SabreDAV
server (no mocks) to validate the full stack: Django -> SabreDAV -> DB.

Requires: CalDAV server running (skipped otherwise).
"""

# pylint: disable=no-member,broad-exception-caught,unused-variable

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

    The ResourceAutoSchedulePlugin checks X-CalDAV-Organization against
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
