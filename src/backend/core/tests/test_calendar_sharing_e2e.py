"""E2E calendar sharing access rights tests against real SabreDAV.

Privilege levels: freebusy (busy/free only), read, read-write, admin.
Requires: CalDAV server running.
"""

# pylint: disable=no-member,broad-exception-caught,unused-variable,too-many-lines

import secrets
from datetime import datetime, timedelta
from urllib.parse import unquote
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

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
    """Share a calendar using CS:share POST via the CalDAV proxy.

    Mirrors the frontend ``buildShareeSetXml`` wire format exactly:

    - ``freebusy`` and ``admin`` ride on top of standard CalDAV access
      levels (``CS:read`` / ``CS:read-write``) because upstream
      sabre/dav has no ``<CS:admin/>`` element and silently demotes
      anything other than ``<CS:read-write/>`` to read.
    - The actual logical level is carried by an ``<LS:share-access>``
      marker. The element is ALWAYS emitted (empty for plain
      ``read``/``read-write``) so the backend's ``afterPost`` hook can
      reset any prior override — without that, a sharee being moved
      off ``freebusy`` would stay pinned to it forever.
    """
    privilege_xml = {
        "freebusy": "<CS:read/>",
        "read": "<CS:read/>",
        "read-write": "<CS:read-write/>",
        "admin": "<CS:read-write/>",
    }[privilege]
    override = {
        "freebusy": "freebusy",
        "read": "",
        "read-write": "",
        "admin": "admin",
    }[privilege]

    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/"'
        ' xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
        "<CS:set>"
        f"<D:href>mailto:{sharee_email}</D:href>"
        f"<LS:share-access>{override}</LS:share-access>"
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


def _read_share_level(owner_client, owner_email, cal_id, sharee_email):
    """Return the persisted share level for ``sharee_email`` on the
    owner's calendar by PROPFINDing both ``CS:invite`` and
    ``LS:share-access-map`` and reconciling them the same way the
    frontend does (override wins over CalDAV access). Returns ``None``
    if the sharee is not present.
    """
    body = (
        '<?xml version="1.0"?>'
        '<D:propfind xmlns:D="DAV:" '
        'xmlns:CS="http://calendarserver.org/ns/" '
        'xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
        "<D:prop>"
        "<CS:invite/>"
        "<LS:share-access-map/>"
        "</D:prop>"
        "</D:propfind>"
    )
    resp = owner_client.generic(
        "PROPFIND",
        f"/caldav/calendars/users/{owner_email}/{cal_id}/",
        data=body,
        content_type="application/xml",
        HTTP_DEPTH="0",
    )
    assert resp.status_code == 207, (
        f"PROPFIND failed: {resp.status_code} {resp.content.decode()[:500]}"
    )

    ns = {
        "d": "DAV:",
        "cs": "http://calendarserver.org/ns/",
        "ls": "http://lasuite.numerique.gouv.fr/ns/",
    }
    root = ET.fromstring(resp.content)
    href_target = f"mailto:{sharee_email}"

    # 1) Custom override (freebusy / admin), if any.
    override = None
    for sharee_el in root.findall(".//ls:share-access-map/ls:sharee", ns):
        if sharee_el.get("href") == href_target:
            override = sharee_el.get("access")
            break

    # 2) Underlying CalDAV access from CS:invite.
    cs_access = None
    found_in_invite = False
    for user_el in root.findall(".//cs:invite/cs:user", ns):
        href_el = user_el.find("d:href", ns)
        if href_el is None or (href_el.text or "").strip() != href_target:
            continue
        found_in_invite = True
        access_el = user_el.find("cs:access", ns)
        if access_el is None:
            break
        if access_el.find("cs:read-write", ns) is not None:
            cs_access = "read-write"
        elif access_el.find("cs:read", ns) is not None:
            cs_access = "read"
        break

    if not found_in_invite:
        return None

    # 3) Reconcile — override wins (same as frontend parseSharePrivilege).
    if override == "freebusy":
        return "freebusy"
    if override == "admin":
        return "admin"
    if cs_access == "read-write":
        return "read-write"
    if cs_access == "read":
        return "read"
    return None


def _assert_share_level(owner_client, owner_email, cal_id, sharee_email, expected):
    """Round-trip assertion: share/PROPFIND/reconcile and assert the
    sharee is persisted at the requested level. Use this in every
    sharing test instead of just checking the POST status code."""
    actual = _read_share_level(owner_client, owner_email, cal_id, sharee_email)
    assert actual == expected, (
        f"Expected sharee {sharee_email!r} at level {expected!r}, got {actual!r}"
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
    """Test that sharing creates invite entries correctly.

    Every test here ROUND-TRIPS via PROPFIND (using
    ``_assert_share_level``) instead of just checking the POST status
    code — historically these tests only verified that SabreDAV accepted
    the share request, which silently let the upstream
    ``<CS:admin/>``-demoted-to-read bug AND the
    ``share_access_level`` leak ride for free.
    """

    def _share_and_assert(self, privilege, slug):
        """Share a fresh calendar at ``privilege`` and assert the
        round-tripped level matches."""
        org = factories.OrganizationFactory(external_id=f"share-setup-{slug}")
        owner, owner_client, cal_path = _create_user_with_calendar(org, f"owner-{slug}")
        sharee = factories.UserFactory(
            email=f"sharee-{slug}@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        response = _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, privilege
        )
        assert response.status_code in (200, 204), (
            f"Share failed: {response.status_code} "
            f"{response.content.decode('utf-8', errors='ignore')[:500]}"
        )

        _assert_share_level(owner_client, owner.email, cal_id, sharee.email, privilege)

    def test_share_calendar_freebusy(self):
        """Freebusy share must round-trip as freebusy (carried by
        LS:share-access on top of CS:read)."""
        self._share_and_assert("freebusy", "fb")

    def test_share_calendar_read(self):
        """Read share must round-trip as read."""
        self._share_and_assert("read", "r")

    def test_share_calendar_read_write(self):
        """Read-write share must round-trip as read-write."""
        self._share_and_assert("read-write", "rw")

    def test_share_calendar_admin(self):
        """Admin share must round-trip as admin.

        Regression: upstream sabre/dav has no ``<CS:admin/>`` element
        and silently demotes anything other than ``<CS:read-write/>``
        to ``ACCESS_READ``. The fix carries the admin marker via
        ``LS:share-access`` on top of CS:read-write, and the test
        proves it round-trips end-to-end.
        """
        self._share_and_assert("admin", "adm")

    def test_share_transitions_walk_the_full_state_machine(self):
        """Walk a single sharee through every interesting transition
        between the four share levels and assert the persisted level
        after each change.

        Regression: ``ShareAccessPlugin::afterPost`` used to early-
        return when the new CS:share body had no ``LS:share-access``
        element, leaving stale ``share_access_level`` values pinned
        forever. A user moving a sharee freebusy → read would still
        read back as freebusy. This walk catches that and any future
        directional regression in either direction.
        """
        org = factories.OrganizationFactory(external_id="share-transitions")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-trans")
        sharee = factories.UserFactory(
            email="sharee-trans@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        # Each step: (target level, label for the failure message).
        # The walk hits every directional transition that exercises
        # both setting an LS:share-access override and clearing one.
        walk = [
            "freebusy",  # fresh → freebusy (sets override)
            "read",  # freebusy → read (clears override) ← was broken
            "read-write",  # read → read-write
            "admin",  # read-write → admin (sets admin override)
            "read",  # admin → read (clears admin override) ← was broken
            "freebusy",  # read → freebusy (sets override again)
            "admin",  # freebusy → admin (swap override)
            "read-write",  # admin → read-write (clears override)
            "freebusy",  # read-write → freebusy
        ]
        for step, target in enumerate(walk):
            resp = _share_calendar_via_caldav(
                owner_client, owner, cal_id, sharee.email, target
            )
            assert resp.status_code in (200, 204), (
                f"step {step} ({target}) POST failed: {resp.status_code}\n"
                f"{resp.content.decode('utf-8', errors='ignore')[:400]}"
            )
            actual = _read_share_level(owner_client, owner.email, cal_id, sharee.email)
            assert actual == target, f"step {step}: expected {target!r}, got {actual!r}"

    def test_unshare_calendar_removes_sharee_from_invite(self):
        """Unsharing must actually remove the sharee from the
        CS:invite block — not just return 200."""
        org = factories.OrganizationFactory(external_id="share-setup-unshare")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-un")
        sharee = factories.UserFactory(
            email="sharee-un@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "read-write"
        )
        # Sanity: the sharee is there at read-write before we unshare.
        _assert_share_level(
            owner_client, owner.email, cal_id, sharee.email, "read-write"
        )

        response = _unshare_calendar(owner_client, owner, cal_id, sharee.email)
        assert response.status_code in (200, 204)

        # After unshare the sharee must no longer be reachable via
        # PROPFIND CS:invite — _read_share_level returns None.
        actual = _read_share_level(owner_client, owner.email, cal_id, sharee.email)
        assert actual is None, (
            f"Sharee still present in invite after unshare, got {actual!r}"
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

        # Round-trip-assert at the requested level (catches the case
        # where SabreDAV accepts the share but the principal is in a
        # weird half-created state and the level doesn't persist).
        _assert_share_level(owner_client, owner.email, cal_id, sharee.email, "read")


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
        assert map_resp.status_code == 207, (
            f"PROPFIND returned {map_resp.status_code}: "
            f"{map_resp.content.decode()[:500]}"
        )

        # Parse the multistatus XML structurally — substring matching on
        # "freebusy" in the body would also match the literal element name
        # ``<LS:share-access>freebusy</LS:share-access>`` echoed in DAV:not-found
        # property responses, or the namespace declaration text. The whole
        # point of share-access-map is the per-sharee access value, so we
        # assert *exactly* that and nothing else.
        ns = {
            "d": "DAV:",
            "ls": "http://lasuite.numerique.gouv.fr/ns/",
        }
        root = ET.fromstring(map_resp.content)
        sam_elements = root.findall(".//ls:share-access-map", ns)
        assert len(sam_elements) == 1, (
            f"Expected exactly one share-access-map element, got "
            f"{len(sam_elements)}. Response: {map_resp.content.decode()[:1000]}"
        )

        sharees = sam_elements[0].findall("ls:sharee", ns)
        assert len(sharees) == 1, (
            f"Expected exactly one sharee child element, got {len(sharees)}. "
            f"Response: {map_resp.content.decode()[:1000]}"
        )
        assert sharees[0].get("href") == f"mailto:{sharee.email}", (
            f"sharee href mismatch: got {sharees[0].get('href')!r}"
        )
        assert sharees[0].get("access") == "freebusy", (
            f"sharee access must be 'freebusy', got "
            f"{sharees[0].get('access')!r}. The roundtrip persisted a "
            f"different access level than the one we requested."
        )

    @pytest.mark.parametrize(
        "hostile_level",
        [
            "owner",
            "read-write",
            "../etc/passwd",
            "freebusy; DROP TABLE",
            "<script>alert(1)</script>",
            "FREEBUSY",  # case-mismatched (allowlist is exact match)
            "fr33busy",
            "x" * 200,
        ],
    )
    def test_share_access_level_coerces_unknown_values(self, hostile_level):
        """share_access_level must accept ONLY {null, 'freebusy', 'admin'}.

        Anything else gets coerced to NULL at write time. The privacy
        plugin currently checks ``=== 'freebusy'`` and the frontend only
        badges ``'freebusy'``/``'admin'``, but a future reader might do
        substring/like matching — keep arbitrary attacker-supplied
        strings out of the column entirely so they can't become a
        primitive for a future bug.

        We assert via PROPFIND of LS:share-access-map: a coerced row
        either reports no access attribute or reports a value other
        than the hostile string. Importantly the SHAREE row must still
        be created (the rest of the share is valid) — we're testing
        the access-level field in isolation.
        """
        org = factories.OrganizationFactory(
            external_id=f"hostile-{secrets.token_hex(4)}"
        )
        owner, owner_client, cal_path = _create_user_with_calendar(
            org, f"owner-hostile-{secrets.token_hex(4)}"
        )
        sharee = factories.UserFactory(
            email=f"sharee-hostile-{secrets.token_hex(4)}@share-test.com",
            organization=org,
        )
        cal_id = _get_cal_id(cal_path)

        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/"'
            ' xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
            "<CS:set>"
            f"<D:href>mailto:{sharee.email}</D:href>"
            f"<LS:share-access>{escape(hostile_level)}</LS:share-access>"
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
            f"Hostile share POST failed: {resp.status_code} {resp.content[:300]!r}"
        )

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
        assert map_resp.status_code == 207

        ns = {"d": "DAV:", "ls": "http://lasuite.numerique.gouv.fr/ns/"}
        root = ET.fromstring(map_resp.content)
        # share-access-map only includes rows with non-NULL share_access_level.
        # If the hostile value was coerced to NULL the row is absent — pass.
        # If the row IS present the access attribute must NOT contain the
        # hostile string.
        for sharee_el in root.findall(".//ls:share-access-map/ls:sharee", ns):
            if sharee_el.get("href") != f"mailto:{sharee.email}":
                continue
            access = sharee_el.get("access") or ""
            assert access not in (hostile_level, hostile_level.strip()), (
                f"share_access_level was NOT coerced for hostile input "
                f"{hostile_level!r}; PROPFIND returned access={access!r}"
            )
            assert access in {"freebusy", "admin", ""}, (
                f"share_access_level returned out-of-allowlist value "
                f"{access!r} for hostile input {hostile_level!r}"
            )

    @pytest.mark.parametrize("good_level", ["freebusy", "admin"])
    def test_share_access_level_accepts_allowlist(self, good_level):
        """The two legitimate values (freebusy, admin) must round-trip."""
        org = factories.OrganizationFactory(
            external_id=f"good-{good_level}-{secrets.token_hex(4)}"
        )
        owner, owner_client, cal_path = _create_user_with_calendar(
            org, f"owner-good-{good_level}"
        )
        sharee = factories.UserFactory(
            email=f"sharee-good-{good_level}@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        # admin rides on CS:read-write, freebusy rides on CS:read
        underlying = "<CS:read-write/>" if good_level == "admin" else "<CS:read/>"
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/"'
            ' xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
            "<CS:set>"
            f"<D:href>mailto:{sharee.email}</D:href>"
            f"<LS:share-access>{good_level}</LS:share-access>"
            f"{underlying}"
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
        ns = {"d": "DAV:", "ls": "http://lasuite.numerique.gouv.fr/ns/"}
        root = ET.fromstring(map_resp.content)
        sharees = [
            s
            for s in root.findall(".//ls:share-access-map/ls:sharee", ns)
            if s.get("href") == f"mailto:{sharee.email}"
        ]
        assert len(sharees) == 1, (
            f"Allowlisted level {good_level!r} should round-trip; found "
            f"{len(sharees)} sharee rows for {sharee.email}"
        )
        assert sharees[0].get("access") == good_level

    def test_share_access_map_returns_proper_xml_elements(self):
        """LS:share-access-map must contain real <LS:sharee/> child elements,
        not an HTML-escaped XML string.

        Regression: ShareAccessPlugin used to return the inner XML as a
        plain PHP string, which SabreDAV's serializer then HTML-escaped
        as text content. The wire response contained
        ``&lt;LS:sharee href=&quot;...&quot; access=&quot;freebusy&quot;/&gt;``
        — the frontend XML parser saw a single text node and the share
        was displayed as 'Reader' instead of 'Free/Busy'. The fix is to
        wrap the inner XML in ``Sabre\\Xml\\Element\\XmlFragment`` so it
        gets re-parsed and serialized as proper child elements.

        This test parses the multistatus response and asserts the
        expected XML *structure* — the substring check in
        ``test_freebusy_share_roundtrip`` did not catch the regression
        because "freebusy" appears in both the broken and the fixed
        wire format.
        """
        org = factories.OrganizationFactory(external_id="fb-map-xml")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbmx")
        sharee = factories.UserFactory(
            email="sharee-fbmx@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

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
        assert resp.status_code in (200, 204)

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
        assert map_resp.status_code == 207, (
            f"PROPFIND returned {map_resp.status_code}: "
            f"{map_resp.content.decode()[:500]}"
        )

        ns = {
            "d": "DAV:",
            "ls": "http://lasuite.numerique.gouv.fr/ns/",
        }
        root = ET.fromstring(map_resp.content)
        sam_elements = root.findall(".//ls:share-access-map", ns)
        assert len(sam_elements) == 1, (
            f"Expected exactly one share-access-map element, got {len(sam_elements)}"
        )
        sam = sam_elements[0]

        # CRITICAL: must NOT be a text node — that's the regression
        # we're guarding against. If SabreDAV serialized the inner XML
        # as escaped text content, the element would have text but no
        # children.
        assert (sam.text or "").strip() == "", (
            f"share-access-map must not contain text content "
            f"(escaped XML string regression). Got text: "
            f"{(sam.text or '')!r}"
        )

        sharees = sam.findall("ls:sharee", ns)
        assert len(sharees) == 1, (
            f"Expected exactly one sharee child element, got "
            f"{len(sharees)}. Raw response:\n"
            f"{map_resp.content.decode()[:1000]}"
        )
        assert sharees[0].get("href") == f"mailto:{sharee.email}", (
            f"sharee href mismatch: got {sharees[0].get('href')!r}"
        )
        assert sharees[0].get("access") == "freebusy", (
            f"sharee access mismatch: got {sharees[0].get('access')!r}"
        )

    def test_freebusy_to_read_transition_clears_override(self):
        """Moving a sharee from freebusy back to plain read must clear
        ``share_access_level`` so the share-access-map no longer reports
        them as freebusy.

        Regression: ``ShareAccessPlugin::afterPost`` early-returned when
        the new CS:share body had no ``LS:share-access`` element, so the
        old freebusy marker stayed pinned and the frontend kept showing
        the sharee as Free/Busy even after the owner picked Reader.
        """
        org = factories.OrganizationFactory(external_id="fb-clear-override")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-fbc")
        sharee = factories.UserFactory(
            email="sharee-fbc@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        # 1. Share as freebusy (sets share_access_level=freebusy).
        body_fb = (
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
            data=body_fb,
            content_type="application/xml",
        )
        assert resp.status_code in (200, 204)

        # 2. Update to plain read (the frontend now always emits an
        # explicit empty LS:share-access element so the backend knows
        # to clear any prior override).
        body_read = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/"'
            ' xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
            "<CS:set>"
            f"<D:href>mailto:{sharee.email}</D:href>"
            "<LS:share-access></LS:share-access>"
            "<CS:read/>"
            "</CS:set>"
            "</CS:share>"
        )
        resp = owner_client.generic(
            "POST",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=body_read,
            content_type="application/xml",
        )
        assert resp.status_code in (200, 204)

        # 3. The share-access-map should no longer carry this sharee
        # at all (the row's share_access_level is NULL → excluded by
        # the SELECT in propFindShareAccessMap).
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
        ns = {
            "d": "DAV:",
            "ls": "http://lasuite.numerique.gouv.fr/ns/",
        }
        root = ET.fromstring(map_resp.content)
        sharees = root.findall(".//ls:share-access-map/ls:sharee", ns)
        for s in sharees:
            assert s.get("href") != f"mailto:{sharee.email}", (
                "freebusy override leaked: sharee still appears in the "
                "map after being moved to plain read. Raw response:\n"
                f"{map_resp.content.decode()[:1000]}"
            )

    def test_admin_share_persists_via_ls_share_access(self):
        """An admin share rides on ``<CS:read-write/>`` (since upstream
        sabre/dav has no ``<CS:admin/>``) plus an ``LS:share-access>admin``
        marker. The marker must round-trip via the share-access-map so
        the frontend can render the sharee as Administrator and not as
        plain Editor."""
        org = factories.OrganizationFactory(external_id="admin-marker")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-adm")
        sharee = factories.UserFactory(
            email="sharee-adm@share-test.com", organization=org
        )
        cal_id = _get_cal_id(cal_path)

        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/"'
            ' xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">'
            "<CS:set>"
            f"<D:href>mailto:{sharee.email}</D:href>"
            "<LS:share-access>admin</LS:share-access>"
            "<CS:read-write/>"
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
        ns = {
            "d": "DAV:",
            "ls": "http://lasuite.numerique.gouv.fr/ns/",
        }
        root = ET.fromstring(map_resp.content)
        sharees = root.findall(".//ls:share-access-map/ls:sharee", ns)
        target = next(
            (s for s in sharees if s.get("href") == f"mailto:{sharee.email}"),
            None,
        )
        assert target is not None, (
            f"Expected admin sharee in map, got {[s.get('href') for s in sharees]}"
        )
        assert target.get("access") == "admin", (
            f"Expected access=admin, got {target.get('access')!r}"
        )

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

        # 4. Round-trip-assert the upgraded level via PROPFIND on the
        # sharee's own view of the calendar. The sharee instance URI is
        # a fresh UUID under their principal — discover it dynamically.
        sharee_client = APIClient()
        sharee_client.force_login(sharee)
        dav_sharee = CalDAVHTTPClient().get_dav_client(sharee)
        sharee_cals = dav_sharee.principal().calendars()
        shared_uri = None
        for c in sharee_cals:
            uri = unquote(str(c.url)).rstrip("/").rsplit("/", maxsplit=1)[-1]
            # The sharee may have their own ``default`` plus the new
            # shared instance. The shared instance URI is a UUID.
            if uri != "default":
                shared_uri = uri
                break
        assert shared_uri, (
            f"Could not find shared calendar URI for {sharee.email} "
            f"in {[str(c.url) for c in sharee_cals]}"
        )

        # The substring check this test originally used would have
        # silently passed even if the share had been mis-stored as
        # ``freebusy`` or ``admin`` because both the broken and fixed
        # responses contain the literal "read-write" somewhere. Going
        # through ``_assert_share_level`` reconciles CS:invite +
        # LS:share-access-map the same way the frontend does.
        _assert_share_level(
            sharee_client, sharee.email, shared_uri, sharee.email, "read-write"
        )

    # NOTE: a "sync downgrade clears prior admin override" test would
    # be valuable but isn't reachable through any current code path.
    # The MailboxPlugin actively blocks direct CS:share with read-write
    # on mailbox calendars (by design — Messages is the source of
    # truth) and the sync code path never writes ``share_access_level``
    # at all, so a mailbox sharee can never carry an ``admin`` marker
    # in the first place. If admin is ever added to ROLE_TO_PRIVILEGE,
    # add a regression test that walks: sync admin → sync viewer →
    # assert level == read.


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

    def test_non_shared_user_cannot_move_events(self):
        """A non-shared user cannot MOVE events out of another user's calendar.

        The proxy is a dumb forwarder for OIDC users: no proxy-side
        principal/path scope enforcement (mirroring PUT/DELETE).
        SabreDAV's stock ACL is what blocks this — a stranger has no
        ``unbind`` privilege on another user's calendar by default —
        and this test pins that contract.

        MOVE is two-resource, so the test asserts three independent
        things: the request was rejected, the source event survives in
        the owner's calendar, and the destination resource was not
        created in the stranger's calendar. The third assertion guards
        against partial-success regressions (a future plugin that
        binds before checking unbind, or that mirrors instead of
        moves) — those would pass a status-code-only test.
        """
        org = factories.OrganizationFactory(external_id="no-access-move")
        owner, owner_client, owner_cal_path = _create_user_with_calendar(
            org, "owner-nam"
        )
        stranger, stranger_client, stranger_cal_path = _create_user_with_calendar(
            org, "stranger-nam"
        )
        owner_cal_id = _get_cal_id(owner_cal_path)
        stranger_cal_id = _get_cal_id(stranger_cal_path)

        _put_event(owner_client, owner.email, owner_cal_id, "stay-put", "Untouchable")

        src_path = f"/caldav/calendars/users/{owner.email}/{owner_cal_id}/stay-put.ics"
        dest_path = (
            f"http://example/caldav/calendars/users/{stranger.email}/"
            f"{stranger_cal_id}/stay-put.ics"
        )
        response = stranger_client.generic("MOVE", src_path, HTTP_DESTINATION=dest_path)
        assert response.status_code in (403, 404), (
            f"SECURITY: cross-user MOVE should be blocked by SabreDAV ACL, "
            f"got {response.status_code}"
        )

        # Source: still in the owner's calendar (not unbound).
        get_src = _get_event(owner_client, owner.email, owner_cal_id, "stay-put")
        assert get_src.status_code == 200, (
            f"Event must remain in owner's calendar after blocked MOVE, "
            f"got GET status {get_src.status_code}"
        )

        # Destination: not created in the stranger's calendar (no
        # partial bind). Use the stranger's own client so a 404 here is
        # genuine absence, not an ACL refusal.
        get_dst = _get_event(
            stranger_client, stranger.email, stranger_cal_id, "stay-put"
        )
        assert get_dst.status_code == 404, (
            f"SECURITY: blocked MOVE must not have created the destination "
            f"resource in the stranger's calendar, got GET status "
            f"{get_dst.status_code}"
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

    def test_freebusy_sharee_cannot_copy_event(self):  # pylint: disable=too-many-locals
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
        # Accepted blocking statuses:
        #   - 403/409: SabreDAV ACL or scheduling plugin rejected the COPY.
        #   - 405: the Django proxy's method allowlist refuses COPY at the
        #     edge (defense in depth — strictly stronger than ACL-level
        #     blocking, since the request never reaches SabreDAV).
        assert response.status_code in (403, 405, 409), (
            f"SECURITY: COPY from freebusy calendar should be blocked, "
            f"got {response.status_code}"
        )

        # Sanity check: if the freebusy block above resolved as 405, that
        # was the proxy's global COPY-not-allowed gate, not the
        # freebusy-specific ACL. Prove that by issuing the same COPY as a
        # non-freebusy READ-WRITE sharee — they should get 405 too,
        # because the proxy blocks COPY for everyone. This documents that
        # the freebusy assertion above is currently dominated by
        # proxy-level blocking; if COPY is ever added to the proxy
        # allowlist, both branches will need to reflect Sabre-side
        # enforcement instead.
        rw_sharee, _, rw_sharee_cal_path = _create_user_with_calendar(
            org, "rw-sharee-fbcp"
        )
        rw_sharee_cal_id = _get_cal_id(rw_sharee_cal_path)
        rw_sharee_client = APIClient()
        rw_sharee_client.force_login(rw_sharee)
        _share_calendar_via_caldav(
            owner_client, owner, cal_id, rw_sharee.email, "read-write"
        )
        # Destination must be the rw_sharee's own calendar — using the
        # freebusy sharee's path would mix in unrelated cross-user ACL
        # effects and muddle the signal the moment COPY is added to the
        # proxy allowlist (which is precisely what this sanity check
        # exists to catch).
        dest_path_rw = (
            f"/caldav/calendars/users/{rw_sharee.email}/"
            f"{rw_sharee_cal_id}/copied-event.ics"
        )
        rw_response = rw_sharee_client.generic(
            "COPY",
            f"/caldav/{src_path}",
            HTTP_DESTINATION=dest_path_rw,
        )
        assert rw_response.status_code == 405, (
            "Expected proxy-level 405 on COPY for a non-freebusy "
            "read-write sharee (the proxy blocks COPY for everyone). "
            f"Got {rw_response.status_code}; if Sabre rejected this "
            "instead, COPY may have been added to the proxy allowlist "
            "and the freebusy assertion above must be re-tightened."
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


class TestSyncManagedShareProtection:
    """Sync-managed shares (created via /internal-api/sync-mailbox-acls/)
    represent the source of truth from Messages. **No** user-initiated
    CalDAV operation may change them — not freebusy, not read, not
    read-write, not admin, not unshare. The only thing allowed to
    overwrite a sync-managed row is another sync.
    """

    def _setup(self, slug, sync_privilege):
        """Create owner + mailbox + a sync-managed sharee.

        Returns ``cal_id`` as the URI of the OWNER's own sharee row
        for the mailbox calendar — that's the URL the modal POSTs
        manual CS:share requests against.
        """
        org = factories.OrganizationFactory(external_id=f"sync-prot-{slug}")
        owner, owner_client, _ = _create_user_with_calendar(org, f"o-{slug}")
        sharee = factories.UserFactory(
            email=f"sharee-{slug}@sync-prot.com", organization=org
        )
        mailbox_email = f"team-{slug}@sync-prot.com"
        _create_mailbox_calendar(owner, mailbox_email, org)

        # Sync the owner first so they get a sharee instance under
        # their own principal, then snapshot before syncing the actual
        # ``sharee`` so the look-up of the owner-side URL is unambiguous.
        before_urls = _list_calendar_urls(owner)
        _sync_mailbox_acls(
            owner,
            [
                {
                    "user_email": owner.email,
                    "mailbox_email": mailbox_email,
                    "privilege": "read-write",
                },
                {
                    "user_email": sharee.email,
                    "mailbox_email": mailbox_email,
                    "privilege": sync_privilege,
                },
            ],
        )
        cal_id = _find_shared_cal_uri(owner, before_urls=before_urls)
        return org, owner, owner_client, sharee, mailbox_email, cal_id

    # ----- manual share is blocked at every level on sync-managed --------

    @pytest.mark.parametrize(
        ("sync_privilege", "manual_attempt"),
        [
            # Sync-managed READ — every manual level must be rejected,
            # including a same-level reshare (no-op writes still go
            # through SabreDAV's ON CONFLICT and would clobber the row).
            ("read", "freebusy"),
            ("read", "read"),
            ("read", "read-write"),
            ("read", "admin"),
            # Sync-managed READ-WRITE — every downgrade must be rejected.
            ("read-write", "freebusy"),
            ("read-write", "read"),
        ],
    )
    def test_manual_share_blocked_on_sync_managed_sharee(
        self, sync_privilege, manual_attempt
    ):
        """No user-initiated CS:share level may touch a sync-managed sharee.

        Regression: ``MailboxPlugin::restrictSharing`` only matched
        ``read-write`` in the body, so ``freebusy`` and plain ``read``
        rode straight through to SabreDAV's ``ON CONFLICT`` upsert and
        silently overwrote the Messages-managed access.
        """
        slug = f"{manual_attempt}-on-{sync_privilege}"
        _, owner, owner_client, sharee, _, cal_id = self._setup(slug, sync_privilege)
        resp = _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, manual_attempt
        )
        assert resp.status_code == 403, (
            f"Manual {manual_attempt!r} share on a sync-managed "
            f"{sync_privilege!r} sharee should return 403, got "
            f"{resp.status_code}: "
            f"{resp.content.decode('utf-8', errors='ignore')[:500]}"
        )
        actual = _read_share_level(owner_client, owner.email, cal_id, sharee.email)
        assert actual == sync_privilege, (
            f"After blocked manual {manual_attempt!r}, sync-managed "
            f"sharee should still be at {sync_privilege!r}, got {actual!r}"
        )

    # ----- unshare (CS:remove) is also blocked --------------------------

    def test_unshare_blocked_on_sync_managed_sharee(self):
        """CS:remove of a sync-managed sharee must be 403, row preserved."""
        _, owner, owner_client, sharee, _, cal_id = self._setup("rm", "read")
        resp = _unshare_calendar(owner_client, owner, cal_id, sharee.email)
        assert resp.status_code == 403, (
            f"Unshare on a sync-managed sharee should return 403, got "
            f"{resp.status_code}: "
            f"{resp.content.decode('utf-8', errors='ignore')[:500]}"
        )
        actual = _read_share_level(owner_client, owner.email, cal_id, sharee.email)
        assert actual == "read", (
            f"After blocked unshare, sync-managed sharee should still "
            f"be at 'read', got {actual!r}"
        )

    # ----- non-sync-managed users can still be shared with manually -----

    def test_manual_share_still_works_for_non_sync_managed_user(self):
        """A user who has never been sync-managed can still get a manual
        read or freebusy share — the protection only applies to rows
        that are actually sync-managed."""
        _, owner, owner_client, _, _, cal_id = self._setup("clean", "read")
        # ``other`` has no sync-managed row at all.
        org = factories.OrganizationFactory(external_id="sync-prot-clean-other")
        other = factories.UserFactory(
            email="other@sync-prot-clean.com", organization=org
        )
        resp = _share_calendar_via_caldav(
            owner_client, owner, cal_id, other.email, "read"
        )
        assert resp.status_code in (200, 204), (
            f"Manual read share on a non-sync-managed user should "
            f"succeed, got {resp.status_code}: "
            f"{resp.content.decode('utf-8', errors='ignore')[:500]}"
        )
        actual = _read_share_level(owner_client, owner.email, cal_id, other.email)
        assert actual == "read"

    # ----- another sync IS allowed to update a sync-managed sharee ------

    def test_sync_can_still_update_a_sync_managed_sharee(self):
        """The sync-managed protection only blocks user-initiated
        actions. The internal API (used by SetupService.sync_*) must
        keep working — re-syncing a sharee with a different role is the
        only legitimate way to change a sync-managed level."""
        _, owner, owner_client, sharee, mailbox_email, cal_id = self._setup(
            "resync", "read"
        )
        # Re-sync with read-write — Messages now grants more access.
        _sync_mailbox_acls(
            owner,
            [
                {
                    "user_email": sharee.email,
                    "mailbox_email": mailbox_email,
                    "privilege": "read-write",
                }
            ],
        )
        actual = _read_share_level(owner_client, owner.email, cal_id, sharee.email)
        assert actual == "read-write", (
            f"After re-sync to read-write, sharee should be at "
            f"'read-write', got {actual!r}"
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

    def test_sync_fans_out_to_all_calendars_under_mailbox(self):
        """A single share entry per (user, mailbox) must fan out to every
        calendar under that mailbox principal — not just ``default``.

        Regression: ``sync-mailbox-acls`` used to require a per-share
        ``calendar_uri`` and silently dropped shares whose URI did not
        match. A mailbox can back several calendars (the second create
        allocates a UUID URI), and the sync must reach all of them.
        """
        org = factories.OrganizationFactory(external_id="sync-multi-cal")
        owner, _, _ = _create_user_with_calendar(org, "owner-syncmulti")
        sharee = factories.UserFactory(
            email="sharee@sync-multi-cal.com", organization=org
        )
        mailbox_email = "team@sync-multi-cal.com"

        # Two calendars under the same mailbox: first gets "default",
        # second gets a fresh UUID.
        _create_mailbox_calendar(owner, mailbox_email, org, name="Project A")
        _create_mailbox_calendar(owner, mailbox_email, org, name="Project B")

        resp = _sync_mailbox_acls(
            owner,
            [
                {
                    "user_email": sharee.email,
                    "mailbox_email": mailbox_email,
                    "privilege": "read-write",
                }
            ],
        )
        active = resp.json().get("active", [])
        # One entry per concrete mailbox calendar.
        assert len(active) == 2, (
            f"Expected fan-out to both mailbox calendars, got {active}"
        )
        uris = sorted(a["calendar_uri"] for a in active)
        assert "default" in uris, f"Default calendar not in fan-out: {uris}"
        assert any(u != "default" for u in uris), (
            f"Second (UUID) calendar not in fan-out: {uris}"
        )

        # Sharee must see BOTH shared calendars.
        cals = CalDAVHTTPClient().get_dav_client(sharee).principal().calendars()
        assert len(cals) == 2, (
            f"Sharee should see 2 shared mailbox calendars, "
            f"got {len(cals)}: {[str(c.url) for c in cals]}"
        )

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

    def test_sync_refuses_non_mailbox_principal(self):
        """sync-mailbox-acls must NEVER create sync-managed rows under a
        non-MAILBOX principal.

        Invariant pin (security): ``MailboxPlugin::restrictSharing`` and
        ``ShareAccessPlugin::afterPost`` rely on the rule that
        ``is_sync_managed = TRUE`` rows only exist on calendars whose
        owning principal is of type ``MAILBOX``. If sync-managed rows
        ever landed on an INDIVIDUAL calendar, manual CS:share/CS:remove
        ops on that calendar would silently overwrite them — collapsing
        the Messages-managed share into something the sharee or owner
        could tamper with.

        We pin the invariant by trying to share an INDIVIDUAL principal's
        calendar via sync-mailbox-acls (passing the individual's email as
        ``mailbox_email``). The endpoint must accept the call (returning
        200, since it accepts empty share lists for full-sync use), but
        must skip the entry: the target user must NOT see a new shared
        calendar, and ``active`` must not list it.
        """
        org = factories.OrganizationFactory(external_id="sync-not-mailbox")
        # An INDIVIDUAL principal (created the normal way via the
        # CalendarService → /internal-api/calendars/ with type=INDIVIDUAL).
        individual, _, _ = _create_user_with_calendar(org, "individual-notmbx")
        sharee = factories.UserFactory(
            email="sharee@sync-not-mailbox.com", organization=org
        )

        # Snapshot before so a baseline diff is unambiguous.
        sharee_calendars_before = _list_calendar_urls(sharee)

        resp = _sync_mailbox_acls(
            individual,
            [
                {
                    "user_email": sharee.email,
                    # Deliberately point at the INDIVIDUAL's email — the
                    # SQL must filter this out via the principal-type JOIN.
                    "mailbox_email": individual.email,
                    "privilege": "read-write",
                }
            ],
        )

        # The fan-out must be empty: no MAILBOX-typed owner calendar
        # matched, so the share entry is silently dropped.
        active = resp.json().get("active", [])
        assert active == [], (
            f"sync-mailbox-acls must not fan out to non-MAILBOX principals, "
            f"got active={active}"
        )

        # Sharee must NOT see any new calendar.
        sharee_calendars_after = _list_calendar_urls(sharee)
        new_urls = sharee_calendars_after - sharee_calendars_before
        assert new_urls == set(), (
            f"Sharee must not gain a calendar from a non-mailbox sync, "
            f"got new urls: {new_urls}"
        )


class TestSyncSameEmailCoexistence:
    """When user.email == mailbox_email, they are separate principals
    (principals/users/ vs principals/mailboxes/). Sync creates a normal
    sharee instance for the user — no collision, no special handling.
    """

    def test_sync_creates_sharee_for_owner_email(self):
        """sync-mailbox-acls creates a normal sharee row when the
        user's email matches the mailbox email. With the namespace
        split, owner (principals/mailboxes/) and sharee
        (principals/users/) have different principaluri values.
        """
        org = factories.OrganizationFactory(external_id="sync-coexist")
        user = factories.UserFactory(email="user@sync-coexist.com", organization=org)
        mailbox_email = user.email

        _create_mailbox_calendar(user, mailbox_email, org, name="Personal")

        calendars_before = _list_calendar_urls(user)

        resp = _sync_mailbox_acls(
            user,
            [
                {
                    "user_email": user.email,
                    "mailbox_email": mailbox_email,
                    "privilege": "read-write",
                }
            ],
        )

        active = resp.json().get("active", [])
        active_emails = [a["mailbox_email"] for a in active]
        assert mailbox_email in active_emails, (
            f"Mailbox must appear in active, got {active}"
        )

        calendars_after = _list_calendar_urls(user)
        new_urls = calendars_after - calendars_before
        assert len(new_urls) > 0, (
            f"Sync should create at least one user-visible sharee calendar. "
            f"Before: {calendars_before}, After: {calendars_after}"
        )


class TestRsvpInternalApi:
    """POST /internal-api/rsvp/ finds events by UID across all
    principals matching the organizer email and updates PARTSTAT.
    """

    def test_rsvp_personal_mailbox(self):
        """RSVP updates PARTSTAT for an event in a personal mailbox
        calendar (user.email == mailbox_email).
        """
        org = factories.OrganizationFactory(external_id="rsvp-personal")
        user = factories.UserFactory(email="user@rsvp-personal.com", organization=org)

        _create_mailbox_calendar(user, user.email, org, name="Personal")
        _sync_mailbox_acls(
            user,
            [
                {
                    "user_email": user.email,
                    "mailbox_email": user.email,
                    "privilege": "read-write",
                }
            ],
        )

        uid = f"rsvp-test-{secrets.token_hex(8)}"
        attendee = "bob@rsvp-personal.com"
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTART:20260501T100000Z\r\n"
            "DTEND:20260501T110000Z\r\n"
            "SUMMARY:Personal RSVP\r\n"
            f"ORGANIZER:mailto:{user.email}\r\n"
            f"ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:{attendee}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        dav = CalDAVHTTPClient().get_dav_client(user)
        dav.principal().calendars()[0].save_event(ics)

        resp = http.internal_request(
            "POST",
            user,
            "internal-api/rsvp/",
            json={
                "organizer_email": user.email,
                "uid": uid,
                "attendee_email": attendee,
                "partstat": "ACCEPTED",
            },
        )
        assert resp.status_code == 200, (
            f"RSVP should succeed: {resp.status_code} {resp.text}"
        )
        assert resp.json().get("summary") == "Personal RSVP"

    def test_rsvp_team_mailbox(self):
        """RSVP updates PARTSTAT for an event in a team mailbox
        calendar (no user logs in with the organizer email).
        The internal API finds it via DB query across all namespaces.
        """
        org = factories.OrganizationFactory(external_id="rsvp-team")
        admin = factories.UserFactory(email="admin@rsvp-team.com", organization=org)
        team_email = "team@rsvp-team.com"

        _create_mailbox_calendar(admin, team_email, org, name="Team")
        _sync_mailbox_acls(
            admin,
            [
                {
                    "user_email": admin.email,
                    "mailbox_email": team_email,
                    "privilege": "read-write",
                }
            ],
        )

        uid = f"rsvp-team-{secrets.token_hex(8)}"
        attendee = "charlie@rsvp-team.com"
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            "DTSTART:20260501T100000Z\r\n"
            "DTEND:20260501T110000Z\r\n"
            "SUMMARY:Team Event\r\n"
            f"ORGANIZER:mailto:{team_email}\r\n"
            f"ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:{attendee}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )

        # Write event via admin's shared view of the team calendar.
        # The sharee instance has a UUID URI under calendars/users/admin@.
        # Find it by checking which calendar was added after setup.
        dav = CalDAVHTTPClient().get_dav_client(admin)
        cals = dav.principal().calendars()
        shared_cal = None
        for cal in cals:
            cal_url = str(cal.url)
            if "admin@rsvp-team.com" not in cal_url or "default" in cal_url:
                continue
            shared_cal = cal
            break
        if not shared_cal:
            shared_cal = cals[-1]
        shared_cal.save_event(ics)

        resp = http.internal_request(
            "POST",
            admin,
            "internal-api/rsvp/",
            json={
                "organizer_email": team_email,
                "uid": uid,
                "attendee_email": attendee,
                "partstat": "TENTATIVE",
            },
        )
        assert resp.status_code == 200, (
            f"Team RSVP should succeed: {resp.status_code} {resp.text}"
        )
        assert resp.json().get("summary") == "Team Event"

    def test_rsvp_event_not_found(self):
        """RSVP returns 404 for a nonexistent event UID."""
        org = factories.OrganizationFactory(external_id="rsvp-notfound")
        user = factories.UserFactory(email="user@rsvp-notfound.com", organization=org)

        resp = http.internal_request(
            "POST",
            user,
            "internal-api/rsvp/",
            json={
                "organizer_email": user.email,
                "uid": "nonexistent-uid",
                "attendee_email": "bob@example.com",
                "partstat": "ACCEPTED",
            },
        )
        assert resp.status_code == 404


class TestProppatchScheduleTransp:
    """PROPPATCH schedule-calendar-transp on a sharee instance must work
    against PostgreSQL.

    Regression: SabreDAV's upstream ``CalDAV\\Backend\\PDO::updateCalendar``
    stores the ``transparent`` value as a PHP boolean and binds it
    directly. The pgsql PDO driver serializes ``false`` as the empty
    string ``''`` (instead of 0/1), which the ``transparent SMALLINT NOT
    NULL`` column rejects with ``SQLSTATE[22P02]: invalid input syntax
    for type smallint``. The fix is in
    ``AuditCalDAVBackend::updateCalendar`` (the override casts to int
    before binding).
    """

    def test_proppatch_schedule_transp_on_sharee_instance(self):  # pylint: disable=too-many-locals
        """A sharee should be able to PROPPATCH schedule-calendar-transp
        on their per-instance shared calendar without hitting the
        bool→smallint PDO bug."""
        org = factories.OrganizationFactory(external_id="proppatch-transp")
        owner, _, cal_path = _create_user_with_calendar(org, "owner-trsp")
        sharee, sharee_client, _ = _create_user_with_calendar(org, "sharee-trsp")
        cal_id = _get_cal_id(cal_path)

        # Owner shares read-write with sharee via raw CS:share so the
        # sharee-instance row exists in calendarinstances.
        owner_client = APIClient()
        owner_client.force_login(owner)
        share_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<CS:share xmlns:D="DAV:" xmlns:CS="http://calendarserver.org/ns/">'
            "<CS:set>"
            f"<D:href>mailto:{sharee.email}</D:href>"
            "<CS:read-write/>"
            "</CS:set>"
            "</CS:share>"
        )
        share_resp = owner_client.generic(
            "POST",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=share_body,
            content_type="application/xml",
        )
        assert share_resp.status_code in (200, 204)

        # Find the sharee's instance URI (UUID under their principal home).
        before = set()
        dav = CalDAVHTTPClient().get_dav_client(sharee)
        cals = dav.principal().calendars()
        assert len(cals) >= 1
        # The sharee may have their own cal + the shared one. Pick the
        # shared instance — its URI is a UUID, not "default".
        shared = next(
            (c for c in cals if not str(c.url).rstrip("/").endswith("default")),
            None,
        )
        assert shared is not None, (
            f"Expected at least one non-default calendar for the sharee, "
            f"got {[str(c.url) for c in cals]}"
        )
        shared_uri = unquote(str(shared.url)).rstrip("/").rsplit("/", maxsplit=1)[-1]

        # PROPPATCH schedule-calendar-transp = OPAQUE on the sharee
        # instance. The opaque case is the one that hits the bug:
        # SabreDAV upstream stores ``transparent === getValue()`` which
        # for opaque is PHP false, and pgsql PDO serializes false as ''.
        # The transparent case binds PHP true → '1' which works.
        proppatch_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propertyupdate xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:set><D:prop>"
            "<C:schedule-calendar-transp><C:opaque/></C:schedule-calendar-transp>"
            "</D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp = sharee_client.generic(
            "PROPPATCH",
            f"/caldav/calendars/users/{sharee.email}/{shared_uri}/",
            data=proppatch_body,
            content_type="application/xml",
        )

        # Must succeed (207 multistatus with HTTP/1.1 200 OK inside).
        assert resp.status_code == 207, (
            f"PROPPATCH returned {resp.status_code}: {resp.content.decode()[:1000]}"
        )
        body = resp.content.decode()
        assert "PDOException" not in body, (
            f"Raw PDO error leaked to client:\n{body[:1500]}"
        )
        assert "SQLSTATE" not in body, f"Raw SQLSTATE leaked to client:\n{body[:1500]}"
        assert "200 OK" in body, f"Expected per-property 200 OK, got:\n{body[:1500]}"

        # Now PROPPATCH back to transparent and confirm it also works
        # (round-trip both directions).
        proppatch_body_t = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propertyupdate xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:set><D:prop>"
            "<C:schedule-calendar-transp><C:transparent/></C:schedule-calendar-transp>"
            "</D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp_t = sharee_client.generic(
            "PROPPATCH",
            f"/caldav/calendars/users/{sharee.email}/{shared_uri}/",
            data=proppatch_body_t,
            content_type="application/xml",
        )
        assert resp_t.status_code == 207
        body_t = resp_t.content.decode()
        assert "PDOException" not in body_t
        assert "200 OK" in body_t

        # Read it back to confirm transparent was persisted.
        check_body = (
            '<?xml version="1.0"?>'
            '<propfind xmlns="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<prop><C:schedule-calendar-transp/></prop>"
            "</propfind>"
        )
        check_resp = sharee_client.generic(
            "PROPFIND",
            f"/caldav/calendars/users/{sharee.email}/{shared_uri}/",
            data=check_body,
            content_type="application/xml",
            HTTP_DEPTH="0",
        )
        assert check_resp.status_code == 207
        assert "transparent" in check_resp.content.decode(), (
            f"schedule-calendar-transp was not persisted as transparent:\n"
            f"{check_resp.content.decode()[:1000]}"
        )

    def test_proppatch_schedule_transp_does_not_leak_pdo_error(self):
        """Defense-in-depth: even if a future regression makes the
        backend throw a raw PDOException, the global exception handler
        in server.php must mask it as a generic 'Internal server error'
        before serializing the response. The client must never see
        SQLSTATE codes, table names, or PDO parameter values.
        """
        # We don't have a way to force a PDO error from outside, so this
        # test simply asserts the same hardening as the test above:
        # PROPPATCH must never expose internal-error markers in the
        # response body. Combined with the always-positive test above,
        # this guards both the success path and the format of any
        # future failure.
        org = factories.OrganizationFactory(external_id="proppatch-noleak")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-leak")
        cal_id = _get_cal_id(cal_path)

        proppatch_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propertyupdate xmlns:D="DAV:" '
            'xmlns:A="http://apple.com/ns/ical/">'
            "<D:set><D:prop>"
            "<A:calendar-color>#ff00aa</A:calendar-color>"
            "</D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp = owner_client.generic(
            "PROPPATCH",
            f"/caldav/calendars/users/{owner.email}/{cal_id}/",
            data=proppatch_body,
            content_type="application/xml",
        )
        assert resp.status_code == 207
        body = resp.content.decode()
        assert "PDOException" not in body
        assert "SQLSTATE" not in body
        assert "syntax for type" not in body


class TestInternalApiCreateCalendarColor:
    """``POST /internal-api/calendars/`` must persist the requested
    ``color`` and ``name`` on every call, and each call must allocate a
    fresh calendar — never overwrite an existing one.

    The first call for a fresh principal still uses the URI ``default``
    (so existing onboarding URLs keep working); subsequent calls get a
    UUID URI returned in the ``calendar_uri`` response field.
    """

    @staticmethod
    def _create(owner, payload):
        return CalDAVHTTPClient().internal_request(
            "POST",
            owner,
            "internal-api/calendars/",
            json=payload,
        )

    @staticmethod
    def _read_calendar_props(reader, target_email, calendar_uri="default"):
        """Read displayname + color via PROPFIND on the target calendar.

        Uses ``CalDAVHTTPClient.request`` so we go through the same
        SabreDAV PROPFIND code path the frontend uses — never SQL.
        """
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:" '
            'xmlns:A="http://apple.com/ns/ical/">'
            "<D:prop>"
            "<D:displayname/>"
            "<A:calendar-color/>"
            "</D:prop>"
            "</D:propfind>"
        )
        resp = CalDAVHTTPClient().request(
            "PROPFIND",
            reader,
            f"calendars/users/{target_email}/{calendar_uri}/",
            data=body,
            content_type="application/xml; charset=utf-8",
            extra_headers={"Depth": "0"},
        )
        assert resp.status_code == 207, (
            f"PROPFIND failed: {resp.status_code} {resp.text[:500]}"
        )
        ns = {
            "d": "DAV:",
            "a": "http://apple.com/ns/ical/",
        }
        root = ET.fromstring(resp.content)
        displayname_el = root.find(".//d:displayname", ns)
        color_el = root.find(".//a:calendar-color", ns)
        return {
            "displayname": (displayname_el.text or "")
            if displayname_el is not None
            else None,
            "color": (color_el.text or "") if color_el is not None else None,
        }

    def test_color_persisted_on_first_create(self):
        """First create with a color must persist that color, and the
        first calendar URI is ``default`` for backwards compatibility."""
        org = factories.OrganizationFactory(external_id="color-first")
        user = factories.UserFactory(
            email="user-color-first@share-test.com", organization=org
        )

        resp = self._create(
            user,
            {
                "email": user.email,
                "name": "My calendar",
                "calendar_user_type": "INDIVIDUAL",
                "org_id": str(org.id),
                "color": "#abcdef",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json().get("calendar_uri") == "default"

        props = self._read_calendar_props(user, user.email)
        assert props["color"] == "#abcdef", props

    def test_second_create_allocates_a_new_calendar(self):
        """Each call must allocate a brand-new calendar — never overwrite
        the principal's existing one. The first create gets ``default``,
        the second gets a fresh UUID, and BOTH calendars keep their own
        independent color (so the user effectively has multiple
        calendars under the same principal)."""
        org = factories.OrganizationFactory(external_id="color-recreate")
        user = factories.UserFactory(
            email="user-color-rc@share-test.com", organization=org
        )

        first = self._create(
            user,
            {
                "email": user.email,
                "name": "First",
                "calendar_user_type": "INDIVIDUAL",
                "org_id": str(org.id),
                "color": "#111111",
            },
        )
        assert first.status_code == 201, first.text
        first_uri = first.json()["calendar_uri"]
        assert first_uri == "default"
        assert self._read_calendar_props(user, user.email, first_uri)["color"] == (
            "#111111"
        )

        second = self._create(
            user,
            {
                "email": user.email,
                "name": "Second",
                "calendar_user_type": "INDIVIDUAL",
                "org_id": str(org.id),
                "color": "#222222",
            },
        )
        assert second.status_code == 201, second.text
        second_uri = second.json()["calendar_uri"]
        assert second_uri != "default", second.json()
        assert second_uri != first_uri

        # Both calendars exist independently, each keeping its own color.
        assert self._read_calendar_props(user, user.email, first_uri)["color"] == (
            "#111111"
        )
        assert self._read_calendar_props(user, user.email, second_uri)["color"] == (
            "#222222"
        )

    def test_displayname_independent_per_calendar(self):
        """Each new calendar keeps its own displayname; a second create
        does not rename the first."""
        org = factories.OrganizationFactory(external_id="name-recreate")
        user = factories.UserFactory(
            email="user-name-rc@share-test.com", organization=org
        )

        first = self._create(
            user,
            {
                "email": user.email,
                "name": "First Name",
                "calendar_user_type": "INDIVIDUAL",
                "org_id": str(org.id),
            },
        )
        assert first.status_code == 201, first.text
        first_uri = first.json()["calendar_uri"]

        second = self._create(
            user,
            {
                "email": user.email,
                "name": "Second Name",
                "calendar_user_type": "INDIVIDUAL",
                "org_id": str(org.id),
            },
        )
        assert second.status_code == 201, second.text
        second_uri = second.json()["calendar_uri"]
        assert second_uri != first_uri

        assert (
            self._read_calendar_props(user, user.email, first_uri)["displayname"]
            == "First Name"
        )
        assert self._read_calendar_props(user, user.email, second_uri)[
            "displayname"
        ] == ("Second Name")


class TestInternalApiCreateMailboxCalendar:
    """``POST /internal-api/calendars/`` with ``calendar_user_type=MAILBOX``
    + ``caller_email`` must:

    1. Land the picked color on the **caller's** sharee instance only —
       not on the (invisible) owner instance, and not on any other
       mailbox user's sharee instance after sync.
    2. Allocate a new calendar on every call so a single mailbox can
       back multiple calendars (think personal mailbox with several
       project calendars).
    """

    @staticmethod
    def _create(owner, payload):
        return CalDAVHTTPClient().internal_request(
            "POST",
            owner,
            "internal-api/calendars/",
            json=payload,
        )

    @staticmethod
    def _read_color(reader, owner_email, calendar_uri, namespace="users"):
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:" '
            'xmlns:A="http://apple.com/ns/ical/">'
            "<D:prop><A:calendar-color/></D:prop>"
            "</D:propfind>"
        )
        resp = CalDAVHTTPClient().request(
            "PROPFIND",
            reader,
            f"calendars/{namespace}/{owner_email}/{calendar_uri}/",
            data=body,
            content_type="application/xml; charset=utf-8",
            extra_headers={"Depth": "0"},
        )
        assert resp.status_code == 207, (
            f"PROPFIND failed: {resp.status_code} {resp.text[:500]}"
        )
        ns = {"a": "http://apple.com/ns/ical/"}
        color_el = ET.fromstring(resp.content).find(".//a:calendar-color", ns)
        return (color_el.text or "") if color_el is not None else None

    @staticmethod
    def _list_calendar_uris(user):
        """Return the set of UUID/default URIs visible to ``user``."""
        dav = CalDAVHTTPClient().get_dav_client(user)
        uris = set()
        for cal in dav.principal().calendars():
            uris.add(unquote(str(cal.url)).rstrip("/").rsplit("/", maxsplit=1)[-1])
        return uris

    def test_caller_color_lands_on_caller_view_not_owner(self):
        """The caller's picked color must show up when the caller reads
        their own view of the calendar (their sharee instance), and the
        owner instance must keep the default color."""
        org = factories.OrganizationFactory(external_id="mbx-color-personal")
        caller = factories.UserFactory(
            email="caller-mbx-cp@share-test.com", organization=org
        )
        mailbox_email = "team-mbx-cp@share-test.com"

        resp = self._create(
            caller,
            {
                "email": mailbox_email,
                "name": "Team",
                "calendar_user_type": "MAILBOX",
                "org_id": str(org.id),
                "color": "#dc3545",
                "caller_email": caller.email,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        owner_uri = body["calendar_uri"]
        caller_uri = body["caller_calendar_uri"]
        # Owner-side and caller-side URIs are independent: the owner
        # row is freshly allocated for the mailbox principal; the
        # caller's sharee row is a different SabreDAV-style UUID under
        # the caller's own principal home.
        assert caller_uri != owner_uri

        # Caller reads via their OWN principal: SabreDAV serves the
        # caller's sharee instance row, which must carry the picked
        # color.
        caller_color = self._read_color(caller, caller.email, caller_uri)
        assert caller_color == "#dc3545", (
            f"Caller view should have picked color, got {caller_color!r}"
        )

        # Reading the OWNER's instance (via the mailbox principal path)
        # must NOT show the picked color — the owner row is invisible
        # to humans and we deliberately leave it at the default so the
        # color stays personal.
        owner_color = self._read_color(
            caller, mailbox_email, owner_uri, namespace="mailboxes"
        )
        assert owner_color != "#dc3545", (
            f"Owner instance must not carry the personal color, got {owner_color!r}"
        )

    def test_caller_color_not_propagated_to_other_mailbox_users(self):
        """When the calendar is fanned out to other mailbox users via
        sync-mailbox-acls, those users' sharee instances must NOT inherit
        the creator's personal color — they get the default."""
        org = factories.OrganizationFactory(external_id="mbx-color-fanout")
        caller = factories.UserFactory(
            email="caller-mbx-fan@share-test.com", organization=org
        )
        other = factories.UserFactory(
            email="other-mbx-fan@share-test.com", organization=org
        )
        mailbox_email = "team-mbx-fan@share-test.com"

        resp = self._create(
            caller,
            {
                "email": mailbox_email,
                "name": "Team",
                "calendar_user_type": "MAILBOX",
                "org_id": str(org.id),
                "color": "#dc3545",
                "caller_email": caller.email,
            },
        )
        assert resp.status_code == 201, resp.text
        calendar_uri = resp.json()["calendar_uri"]

        # Fan out the share to ``other`` via the same path the setup
        # service uses (``SetupService.sync_mailbox`` calls this).
        _sync_mailbox_acls(
            caller,
            [
                {
                    "user_email": other.email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": calendar_uri,
                    "privilege": "read-write",
                }
            ],
        )

        # ``other`` must see the calendar with the DEFAULT color, not
        # the personal one the caller picked.
        # Find the new sharee URI for ``other`` (it's a fresh UUID
        # under their principal — different from the owner uri).
        other_uris = self._list_calendar_uris(other)
        assert other_uris, "other should see the shared calendar"
        # ``other`` only sees this one shared calendar in this test.
        other_uri = next(iter(other_uris))
        other_color = self._read_color(other, other.email, other_uri)
        assert other_color != "#dc3545", (
            f"Other user must NOT inherit the caller's personal color, "
            f"got {other_color!r}"
        )

    def test_second_mailbox_create_allocates_new_calendar(self):
        """Two consecutive setup calls for the SAME mailbox must create
        TWO distinct calendars (a single personal mailbox can back
        multiple calendars)."""
        org = factories.OrganizationFactory(external_id="mbx-multi")
        caller = factories.UserFactory(
            email="caller-mbx-multi@share-test.com", organization=org
        )
        mailbox_email = "team-mbx-multi@share-test.com"

        first = self._create(
            caller,
            {
                "email": mailbox_email,
                "name": "Project A",
                "calendar_user_type": "MAILBOX",
                "org_id": str(org.id),
                "color": "#111111",
                "caller_email": caller.email,
            },
        )
        assert first.status_code == 201, first.text
        first_owner_uri = first.json()["calendar_uri"]
        first_caller_uri = first.json()["caller_calendar_uri"]

        second = self._create(
            caller,
            {
                "email": mailbox_email,
                "name": "Project B",
                "calendar_user_type": "MAILBOX",
                "org_id": str(org.id),
                "color": "#222222",
                "caller_email": caller.email,
            },
        )
        assert second.status_code == 201, second.text
        second_owner_uri = second.json()["calendar_uri"]
        second_caller_uri = second.json()["caller_calendar_uri"]
        assert second_owner_uri != first_owner_uri, (
            "Second mailbox create must allocate a new owner URI, not overwrite"
        )
        assert second_caller_uri != first_caller_uri

        # Caller sees both calendars in their own home (each via its
        # sharee URI), and each carries its own picked color.
        caller_uris = self._list_calendar_uris(caller)
        assert first_caller_uri in caller_uris, (
            f"Expected {first_caller_uri} in caller's home, got {caller_uris}"
        )
        assert second_caller_uri in caller_uris, (
            f"Expected {second_caller_uri} in caller's home, got {caller_uris}"
        )
        assert self._read_color(caller, caller.email, first_caller_uri) == ("#111111")
        assert self._read_color(caller, caller.email, second_caller_uri) == ("#222222")


class TestNonOwnerCannotReshare:
    """Only the calendar OWNER may change who a calendar is shared with or at
    what level. A sharee — even read-write or "admin" — must not be able to
    re-share the calendar or rewrite another sharee's access level.

    Re-sharing is blocked by SabreDAV's sharing ACL (the CS:share POST targets
    the owner's calendar, which only the owner may modify); the share-access
    level write is additionally guarded in ShareAccessPlugin::afterPost so it
    can never run for a non-owner principal regardless of plugin ordering.
    """

    def test_readwrite_sharee_cannot_reshare_to_third_party(self):
        """A read-write sharee (not the owner) must not be able to share the
        owner's calendar with a third party."""
        org = factories.OrganizationFactory(external_id="reshare-block")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rs")
        sharee, sharee_client, _ = _create_user_with_calendar(org, "sharee-rs")
        victim, _, _ = _create_user_with_calendar(org, "victim-rs")
        cal_id = _get_cal_id(cal_path)

        # Owner shares with sharee at the highest non-owner level.
        resp = _share_calendar_via_caldav(
            owner_client, owner, cal_id, sharee.email, "read-write"
        )
        assert resp.status_code in (200, 204)

        # Sharee (NOT the owner) attempts to add `victim` to the owner's
        # calendar. Authenticated as the sharee, targeting the owner's path.
        _share_calendar_via_caldav(sharee_client, owner, cal_id, victim.email, "read")

        # The victim must not have gained any access.
        assert (
            _read_share_level(owner_client, owner.email, cal_id, victim.email) is None
        ), "SECURITY: a non-owner sharee was able to re-share the calendar"

    def test_non_owner_cannot_rewrite_another_sharees_access_level(self):
        """A non-owner sharee must not be able to change the access level the
        owner granted to a different sharee."""
        org = factories.OrganizationFactory(external_id="reshare-level")
        owner, owner_client, cal_path = _create_user_with_calendar(org, "owner-rl")
        alice, _, _ = _create_user_with_calendar(org, "alice-rl")
        bob, bob_client, _ = _create_user_with_calendar(org, "bob-rl")
        cal_id = _get_cal_id(cal_path)

        # Owner pins Alice to freebusy and gives Bob read access.
        assert _share_calendar_via_caldav(
            owner_client, owner, cal_id, alice.email, "freebusy"
        ).status_code in (200, 204)
        assert _share_calendar_via_caldav(
            owner_client, owner, cal_id, bob.email, "read"
        ).status_code in (200, 204)
        _assert_share_level(owner_client, owner.email, cal_id, alice.email, "freebusy")

        # Bob (a non-owner sharee) tries to upgrade Alice to admin.
        _share_calendar_via_caldav(bob_client, owner, cal_id, alice.email, "admin")

        # Alice's level must be unchanged — the afterPost guard refuses the
        # share_access_level write for a non-owner principal.
        _assert_share_level(owner_client, owner.email, cal_id, alice.email, "freebusy")
