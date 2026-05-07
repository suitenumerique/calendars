"""Tests for CalDAV proxy view."""

# pylint: disable=no-member,too-many-lines

import base64
import json
from unittest import mock
from xml.etree import ElementTree as ET

from django.conf import settings

import pytest
import responses
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_207_MULTI_STATUS,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
)
from rest_framework.test import APIClient

from core import enums as core_enums
from core import factories
from core import models as core_models
from core.enums import ChannelScope
from core.models import uuid_to_urlsafe
from core.services.caldav_service import CalDAVHTTPClient, validate_caldav_proxy_path


@pytest.mark.django_db
class TestCalDAVProxy:
    """Tests for CalDAVProxyView."""

    def test_proxy_requires_authentication(self):
        """Test that unauthenticated requests return 401."""
        client = APIClient()
        response = client.generic("PROPFIND", "/caldav/")
        assert response.status_code == HTTP_401_UNAUTHORIZED

    @responses.activate
    def test_proxy_forwards_headers_correctly(self):
        """Test that proxy forwards X-LS-User and does NOT forward
        X-Forwarded-* headers.

        SabreDAV builds URLs from ``setBaseUri`` (env-driven) and never
        reads X-Forwarded-* headers, so the proxy deliberately does not
        set them. This test pins that contract: only X-LS-* should land
        on the outgoing request, never the X-Forwarded-* family.
        """
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        # Mock CalDAV server response
        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="PROPFIND",
                url=f"{caldav_url}/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        client.generic("PROPFIND", "/caldav/")

        # Verify request was made to CalDAV server
        assert len(responses.calls) == 1
        request = responses.calls[0].request

        # The authenticated user identity must be forwarded.
        assert request.headers["X-LS-User"] == user.email

        # X-Forwarded-* headers must NOT be present — SabreDAV ignores
        # them and the proxy was simplified to stop sending them.
        assert "X-Forwarded-For" not in request.headers
        assert "X-Forwarded-Host" not in request.headers
        assert "X-Forwarded-Proto" not in request.headers

    @responses.activate
    def test_proxy_ignores_client_sent_x_forwarded_user_header(self):
        """Test that proxy ignores and overwrites any X-LS-User header sent by client.

        This is a security test to ensure that hostile clients cannot impersonate other users
        by sending a malicious X-LS-User header. The proxy should always use the
        authenticated Django user's email, not any header value sent by the client.
        """
        user = factories.UserFactory(email="legitimate@example.com")
        client = APIClient()
        client.force_login(user)

        # Mock CalDAV server response
        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="PROPFIND",
                url=f"{caldav_url}/caldav/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        # Try to send a malicious X-LS-User header as if we were another user
        malicious_email = "attacker@example.com"
        client.generic(
            "PROPFIND",
            "/caldav/",
            HTTP_X_LS_USER=malicious_email,
        )

        # Verify request was made to CalDAV server
        assert len(responses.calls) == 1
        request = responses.calls[0].request

        # Verify that the X-LS-User header uses the authenticated user's email,
        # NOT the malicious header value sent by the client
        assert request.headers["X-LS-User"] == user.email, (
            f"Expected X-LS-User to be {user.email} (authenticated user), "
            f"but got {request.headers.get('X-LS-User')}. "
            f"This indicates a security vulnerability - client-sent headers are being trusted!"
        )
        assert request.headers["X-LS-User"] != malicious_email, (
            "X-LS-User should NOT use client-sent header value"
        )

    def test_proxy_propfind_response_contains_prefixed_urls(self):
        """PROPFIND responses should contain URLs with proxy prefix.

        This test verifies that sabre/dav's BaseUriPlugin correctly uses X-Forwarded-Prefix
        to generate URLs with the proxy prefix. It requires the CalDAV server to be running.
        Note: This test does NOT use @responses.activate as it needs to hit the real server.
        """
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        # Make actual request to CalDAV server through proxy
        # The server should use X-Forwarded-Prefix to generate URLs
        propfind_body = (
            '<?xml version="1.0"?>'
            '<propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>'
        )
        response = client.generic(
            "PROPFIND",
            "/caldav/",
            data=propfind_body,
            content_type="application/xml",
        )

        assert response.status_code == HTTP_207_MULTI_STATUS, (
            f"Expected 207 Multi-Status, got {response.status_code}: "
            f"{response.content.decode('utf-8', errors='ignore')}"
        )

        # Parse the response XML
        root = ET.fromstring(response.content)

        # Find all href elements
        href_elems = root.findall(".//{DAV:}href")
        assert len(href_elems) > 0, "PROPFIND response should contain href elements"

        # Verify all hrefs start with /caldav/ (BaseUriPlugin uses
        # X-Forwarded-Prefix correctly).
        for href_elem in href_elems:
            href = href_elem.text
            assert href and href.startswith("/caldav/"), (
                f"Expected URL to start with /caldav/, "
                f"got {href}. BaseUriPlugin is not using "
                f"X-Forwarded-Prefix correctly. Full response: "
                f"{response.content.decode('utf-8', errors='ignore')}"
            )

    @responses.activate
    def test_proxy_passes_through_calendar_urls(self):
        """Test that calendar URLs in PROPFIND responses are passed through unchanged.

        Since we removed URL rewriting from the proxy, sabre/dav should generate
        URLs with the correct prefix. This test verifies the proxy passes responses through.
        """
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        # Mock CalDAV server PROPFIND response with calendar URL that already has prefix
        # (sabre/dav should generate URLs with prefix when X-Forwarded-Prefix is set)
        caldav_url = settings.CALDAV_URL
        propfind_xml = """<?xml version="1.0"?>
        <multistatus xmlns="DAV:">
            <response>
                <href>/caldav/calendars/users/test@example.com/calendar-id/</href>
                <propstat>
                    <prop>
                        <resourcetype>
                            <collection/>
                            <calendar xmlns="urn:ietf:params:xml:ns:caldav"/>
                        </resourcetype>
                    </prop>
                </propstat>
            </response>
        </multistatus>"""

        responses.add(
            responses.Response(
                method="PROPFIND",
                url=f"{caldav_url}/caldav/",
                status=HTTP_207_MULTI_STATUS,
                body=propfind_xml,
                headers={"Content-Type": "application/xml"},
            )
        )

        response = client.generic("PROPFIND", "/caldav/")

        assert response.status_code == HTTP_207_MULTI_STATUS

        # Parse the response XML
        root = ET.fromstring(response.content)

        # Find the href element
        href_elem = root.find(".//{DAV:}href")
        assert href_elem is not None

        # Verify the URL is passed through unchanged (sabre/dav should generate it with prefix)
        href = href_elem.text
        assert href == "/caldav/calendars/users/test@example.com/calendar-id/", (
            f"Expected URL to be passed through unchanged, got {href}"
        )

    @responses.activate
    def test_proxy_passes_through_namespaced_href_attributes(self):
        """Test that namespaced href attributes (D:href) are passed through unchanged.

        Since we removed URL rewriting from the proxy, sabre/dav should generate
        URLs with the correct prefix. This test verifies the proxy passes responses through.
        """
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        # Mock CalDAV server PROPFIND response with D:href that already has prefix
        # (sabre/dav should generate URLs with prefix when X-Forwarded-Prefix is set)
        caldav_url = settings.CALDAV_URL
        propfind_xml = """<?xml version="1.0"?>
        <multistatus xmlns="DAV:" xmlns:D="DAV:">
            <response>
                <D:href>/caldav/principals/users/test@example.com/</D:href>
                <propstat>
                    <prop>
                        <resourcetype>
                            <principal/>
                        </resourcetype>
                    </prop>
                </propstat>
            </response>
        </multistatus>"""

        responses.add(
            responses.Response(
                method="PROPFIND",
                url=f"{caldav_url}/caldav/",
                status=HTTP_207_MULTI_STATUS,
                body=propfind_xml,
                headers={"Content-Type": "application/xml"},
            )
        )

        response = client.generic("PROPFIND", "/caldav/")

        assert response.status_code == HTTP_207_MULTI_STATUS

        # Parse the response XML
        root = ET.fromstring(response.content)

        # Find the D:href element (namespaced)
        href_elem = root.find(".//{DAV:}href")
        assert href_elem is not None

        # Verify the URL is passed through unchanged (sabre/dav should generate it with prefix)
        href = href_elem.text
        assert href == "/caldav/principals/users/test@example.com/", (
            f"Expected URL to be passed through unchanged, got {href}"
        )

    @responses.activate
    def test_proxy_forwards_path_correctly(self):
        """Test that proxy forwards the path correctly to CalDAV server."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="PROPFIND",
                url=f"{caldav_url}/caldav/principals/users/test@example.com/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        # Request a specific path
        client.generic("PROPFIND", "/caldav/principals/users/test@example.com/")

        # Verify the request was made to the correct URL
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.url == f"{caldav_url}/caldav/principals/users/test@example.com/"

    @responses.activate
    def test_proxy_handles_options_request(self):
        """Test that OPTIONS requests are handled for CORS."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        response = client.options("/caldav/")

        assert response.status_code == HTTP_200_OK
        assert "Access-Control-Allow-Methods" in response
        assert "PROPFIND" in response["Access-Control-Allow-Methods"]

    @pytest.mark.parametrize(
        "method",
        [
            "LOCK",
            "UNLOCK",
            "COPY",
            "ACL",
            "SEARCH",
            "PATCH",
            "BIND",
            "REBIND",
            "UNBIND",
            "ORDERPATCH",
        ],
    )
    def test_proxy_rejects_unknown_methods(self, method):
        """Methods outside the allowlist are rejected with 405 before the
        request ever reaches SabreDAV.

        This is defense in depth: SabreDAV may add plugins (LOCK, ACL
        writes, etc.) over time, but the proxy must opt them in
        explicitly. A 405 here also exposes ``Allow`` so clients can
        discover the supported set.
        """
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        response = client.generic(method, "/caldav/calendars/users/test@example.com/")

        assert response.status_code == 405
        # Allow header advertises the canonical proxy method set.
        allow = response.get("Allow", "")
        for expected in ("MOVE", "PROPFIND", "REPORT", "MKCALENDAR"):
            assert expected in allow

    @responses.activate
    def test_proxy_forwards_move_with_destination_rewrite(self):
        """MOVE forwards Destination/Overwrite to upstream, with the
        public URL in the Destination header rewritten to point at the
        upstream CalDAV server (so SabreDAV recognizes the destination
        as on its own host)."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        source_path = "/caldav/calendars/users/test@example.com/cal-a/event-uid.ics"
        upstream_source = f"{caldav_url}{source_path}"
        upstream_dest = (
            f"{caldav_url}/caldav/calendars/users/test@example.com/cal-b/event-uid.ics"
        )

        responses.add(
            responses.Response(
                method="MOVE",
                url=upstream_source,
                status=201,
                body="",
            )
        )

        # Client sends an absolute URL pointing at the public proxy host;
        # the proxy must rewrite it to the upstream URL before forwarding.
        public_destination = (
            "http://example-public-host/caldav/calendars/users/"
            "test@example.com/cal-b/event-uid.ics"
        )
        response = client.generic(
            "MOVE",
            source_path,
            HTTP_DESTINATION=public_destination,
            HTTP_OVERWRITE="F",
        )

        assert response.status_code == 201
        assert len(responses.calls) == 1
        forwarded = responses.calls[0].request
        assert forwarded.headers["Destination"] == upstream_dest
        assert forwarded.headers["Overwrite"] == "F"

    def test_proxy_rejects_move_with_invalid_destination(self):
        """A Destination pointing at /internal-api/ or with traversal
        must be rejected before forwarding upstream."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        source_path = "/caldav/calendars/users/test@example.com/cal-a/event-uid.ics"

        response = client.generic(
            "MOVE",
            source_path,
            HTTP_DESTINATION="http://example/caldav/internal-api/sync_acls",
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

        response = client.generic(
            "MOVE",
            source_path,
            HTTP_DESTINATION="http://example/caldav/calendars/../etc/passwd",
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

        # Double-encoded traversal: %252e%252e -> %2e%2e -> ..
        response = client.generic(
            "MOVE",
            source_path,
            HTTP_DESTINATION=("http://example/caldav/calendars/%252e%252e/etc/passwd"),
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_proxy_rejects_move_with_empty_destination(self):
        """A MOVE whose Destination resolves to the calendar root (no
        path beyond ``/caldav/``) must be rejected with 400 — the
        current prefix allowlist treats an empty path as valid (it's
        used for the root PROPFIND), so without an explicit empty-path
        check a caller could smuggle a relocation to the upstream root.
        """
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        source_path = "/caldav/calendars/users/test@example.com/cal-a/event-uid.ics"

        # Destination URL with the proxy prefix but nothing beyond.
        response = client.generic(
            "MOVE", source_path, HTTP_DESTINATION="http://example/caldav/"
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

        # Destination URL that resolves to the absolute server root.
        response = client.generic(
            "MOVE", source_path, HTTP_DESTINATION="http://example/"
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_proxy_rejects_move_destination_outside_channel_scope(self):
        """When MOVE is allowed for a channel scope, the destination
        path must be subject to the same scope check as the source.
        Without this, a CALENDAR-scoped channel could MOVE an event
        out of its scoped calendar into another calendar of the same
        user — bypassing the scope.

        MOVE isn't in any production channel scope today, so this test
        patches it in to exercise the destination-scope code path
        directly. If a future PR adds MOVE to a real scope, this test
        keeps the destination check honest.
        """
        user = factories.UserFactory(email="test@example.com")
        channel = factories.ChannelFactory(
            user=user,
            type="caldav",
            scope_level="calendar",
            caldav_path=f"/calendars/users/{user.email}/cal-a/",
            settings={"scopes": ["events:read", "events:write"]},
            is_active=True,
        )
        token = channel.encrypted_settings["token"]
        chan_id = uuid_to_urlsafe(channel.pk)
        creds = base64.b64encode(f"{user.email}:{chan_id}{token}".encode()).decode()

        client = APIClient()
        source_path = f"/caldav/calendars/users/{user.email}/cal-a/event.ics"
        out_of_scope_dest = (
            f"http://example/caldav/calendars/users/{user.email}/cal-b/event.ics"
        )

        # Patch MOVE into the EVENTS_WRITE object scope so we reach the
        # destination check (otherwise we'd 403 at the method gate).
        # The patch target is `core.models` because that module captured
        # its own binding to the dict at import time.
        patched_methods = dict(core_enums.CHANNEL_SCOPE_OBJECT_METHODS)
        patched_methods[ChannelScope.EVENTS_WRITE] = frozenset(
            patched_methods[ChannelScope.EVENTS_WRITE] | {"MOVE"}
        )

        with mock.patch.object(
            core_models, "CHANNEL_SCOPE_OBJECT_METHODS", patched_methods
        ):
            response = client.generic(
                "MOVE",
                source_path,
                HTTP_DESTINATION=out_of_scope_dest,
                HTTP_AUTHORIZATION=f"Basic {creds}",
            )

        assert response.status_code == 403
        assert b"Forbidden destination" in response.content

    def test_proxy_rejects_path_traversal(self):
        """Test that proxy rejects paths with directory traversal."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        response = client.generic("PROPFIND", "/caldav/calendars/../../etc/passwd")
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_proxy_rejects_non_caldav_path(self):
        """Test that proxy rejects paths outside allowed prefixes."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        response = client.generic("PROPFIND", "/caldav/etc/passwd")
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_proxy_rejects_internal_api_path(self):
        """Test that proxy explicitly blocks /internal-api/ paths."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        response = client.generic("POST", "/caldav/internal-api/resources/")
        assert response.status_code == HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCalDAVFreeBusy:
    """Tests for free/busy queries via CalDAV outbox POST."""

    FREEBUSY_REQUEST = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "METHOD:REQUEST\r\n"
        "BEGIN:VFREEBUSY\r\n"
        "DTSTART:20260309T000000Z\r\n"
        "DTEND:20260310T000000Z\r\n"
        "ORGANIZER:mailto:{organizer}\r\n"
        "ATTENDEE:mailto:{attendee}\r\n"
        "END:VFREEBUSY\r\n"
        "END:VCALENDAR"
    )

    FREEBUSY_RESPONSE = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<cal:schedule-response xmlns:d="DAV:" '
        'xmlns:cal="urn:ietf:params:xml:ns:caldav">\n'
        "  <cal:response>\n"
        "    <cal:recipient><d:href>mailto:{attendee}</d:href></cal:recipient>\n"
        "    <cal:request-status>2.0;Success</cal:request-status>\n"
        "    <cal:calendar-data>"
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//SabreDAV//EN\r\n"
        "BEGIN:VFREEBUSY\r\n"
        "DTSTART:20260309T000000Z\r\n"
        "DTEND:20260310T000000Z\r\n"
        "FREEBUSY:20260309T100000Z/20260309T110000Z\r\n"
        "END:VFREEBUSY\r\n"
        "END:VCALENDAR"
        "</cal:calendar-data>\n"
        "  </cal:response>\n"
        "</cal:schedule-response>"
    )

    @responses.activate
    def test_freebusy_post_forwarded_with_correct_content_type(self):
        """POST to outbox should forward text/calendar content-type to CalDAV."""
        user = factories.UserFactory(email="alice@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        outbox_path = f"calendars/users/{user.email}/outbox/"
        responses.add(
            responses.Response(
                method="POST",
                url=f"{caldav_url}/caldav/{outbox_path}",
                status=HTTP_200_OK,
                body=self.FREEBUSY_RESPONSE.format(attendee="bob@example.com"),
                headers={"Content-Type": "application/xml"},
            )
        )

        body = self.FREEBUSY_REQUEST.format(
            organizer=user.email, attendee="bob@example.com"
        )
        response = client.generic(
            "POST",
            f"/caldav/{outbox_path}",
            data=body,
            content_type="text/calendar; charset=utf-8",
        )

        assert response.status_code == HTTP_200_OK
        assert len(responses.calls) == 1

        # Verify content-type is forwarded (not overwritten to application/xml)
        forwarded = responses.calls[0].request
        assert "text/calendar" in forwarded.headers["Content-Type"]

    @responses.activate
    def test_freebusy_post_forwards_body(self):
        """POST to outbox should forward the iCalendar body unchanged."""
        user = factories.UserFactory(email="alice@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        outbox_path = f"calendars/users/{user.email}/outbox/"
        responses.add(
            responses.Response(
                method="POST",
                url=f"{caldav_url}/caldav/{outbox_path}",
                status=HTTP_200_OK,
                body=self.FREEBUSY_RESPONSE.format(attendee="bob@example.com"),
                headers={"Content-Type": "application/xml"},
            )
        )

        body = self.FREEBUSY_REQUEST.format(
            organizer=user.email, attendee="bob@example.com"
        )
        client.generic(
            "POST",
            f"/caldav/{outbox_path}",
            data=body,
            content_type="text/calendar; charset=utf-8",
        )

        # Verify the body was forwarded
        forwarded = responses.calls[0].request
        assert b"BEGIN:VCALENDAR" in forwarded.body
        assert b"VFREEBUSY" in forwarded.body
        assert b"bob@example.com" in forwarded.body

    @responses.activate
    def test_freebusy_post_forwards_auth_headers(self):
        """POST to outbox should include X-LS-User and X-LS-Api-Key."""
        user = factories.UserFactory(email="alice@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        outbox_path = f"calendars/users/{user.email}/outbox/"
        responses.add(
            responses.Response(
                method="POST",
                url=f"{caldav_url}/caldav/{outbox_path}",
                status=HTTP_200_OK,
                body=self.FREEBUSY_RESPONSE.format(attendee="bob@example.com"),
                headers={"Content-Type": "application/xml"},
            )
        )

        body = self.FREEBUSY_REQUEST.format(
            organizer=user.email, attendee="bob@example.com"
        )
        client.generic(
            "POST",
            f"/caldav/{outbox_path}",
            data=body,
            content_type="text/calendar; charset=utf-8",
        )

        forwarded = responses.calls[0].request
        assert forwarded.headers["X-LS-User"] == user.email
        assert forwarded.headers["X-LS-Api-Key"] == settings.CALDAV_OUTBOUND_API_KEY

    @responses.activate
    def test_freebusy_post_returns_schedule_response(self):
        """POST to outbox should return the CalDAV schedule-response XML."""
        user = factories.UserFactory(email="alice@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        outbox_path = f"calendars/users/{user.email}/outbox/"
        response_body = self.FREEBUSY_RESPONSE.format(attendee="bob@example.com")
        responses.add(
            responses.Response(
                method="POST",
                url=f"{caldav_url}/caldav/{outbox_path}",
                status=HTTP_200_OK,
                body=response_body,
                headers={"Content-Type": "application/xml"},
            )
        )

        body = self.FREEBUSY_REQUEST.format(
            organizer=user.email, attendee="bob@example.com"
        )
        response = client.generic(
            "POST",
            f"/caldav/{outbox_path}",
            data=body,
            content_type="text/calendar; charset=utf-8",
        )

        assert response.status_code == HTTP_200_OK
        # Verify the schedule-response is returned to the client
        root = ET.fromstring(response.content)
        ns = {"cal": "urn:ietf:params:xml:ns:caldav", "d": "DAV:"}
        status = root.find(".//cal:request-status", ns)
        assert status is not None
        assert "2.0" in status.text

    def test_freebusy_post_requires_authentication(self):
        """POST to outbox should require authentication."""
        client = APIClient()
        response = client.generic(
            "POST",
            "/caldav/calendars/users/alice@example.com/outbox/",
            data="BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            content_type="text/calendar",
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED

    @responses.activate
    def test_freebusy_post_includes_organization_header(self):
        """POST to outbox forwards X-LS-Org-Id and returns the freebusy
        schedule-response intact.

        Header forwarding is the org-isolation contract — without it,
        FreeBusyOrgScopePlugin can't enforce per-org sharing rules.
        We also assert the proxy returns the schedule-response payload
        unchanged (recipient href, request-status, calendar-data with
        VFREEBUSY) instead of just trusting the upstream status code.
        """
        user = factories.UserFactory(email="alice@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        outbox_path = f"calendars/users/{user.email}/outbox/"
        responses.add(
            responses.Response(
                method="POST",
                url=f"{caldav_url}/caldav/{outbox_path}",
                status=HTTP_200_OK,
                body=self.FREEBUSY_RESPONSE.format(attendee="bob@example.com"),
                headers={"Content-Type": "application/xml"},
            )
        )

        body = self.FREEBUSY_REQUEST.format(
            organizer=user.email, attendee="bob@example.com"
        )
        response = client.generic(
            "POST",
            f"/caldav/{outbox_path}",
            data=body,
            content_type="text/calendar; charset=utf-8",
        )

        # Header forwarding contract.
        forwarded = responses.calls[0].request
        assert forwarded.headers["X-LS-Org-Id"] == str(user.organization_id)

        # Body forwarding / response correctness — the schedule-response
        # must come back to the client intact.
        assert response.status_code == HTTP_200_OK
        root = ET.fromstring(response.content)
        ns = {"cal": "urn:ietf:params:xml:ns:caldav", "d": "DAV:"}

        # Exactly one cal:response per recipient.
        responses_elems = root.findall(".//cal:response", ns)
        assert len(responses_elems) == 1, (
            f"Expected one schedule-response per attendee, got "
            f"{len(responses_elems)}: {response.content[:500]}"
        )

        recipient_href = responses_elems[0].find(".//cal:recipient/d:href", ns)
        assert recipient_href is not None
        assert recipient_href.text == "mailto:bob@example.com"

        status = responses_elems[0].find("cal:request-status", ns)
        assert status is not None
        assert status.text and status.text.startswith("2.0"), (
            f"Expected request-status 2.0 (Success), got {status.text!r}"
        )

        # The cal:calendar-data must contain a VFREEBUSY block (otherwise
        # the freebusy data was stripped or never embedded).
        cal_data = responses_elems[0].find("cal:calendar-data", ns)
        assert cal_data is not None and cal_data.text
        assert "BEGIN:VFREEBUSY" in cal_data.text
        assert "END:VFREEBUSY" in cal_data.text
        assert "FREEBUSY:" in cal_data.text, (
            f"freebusy time block missing from calendar-data: {cal_data.text[:500]}"
        )


class TestValidateCaldavProxyPath:
    """Tests for validate_caldav_proxy_path utility."""

    def test_empty_path_is_valid(self):
        """Empty path should be valid."""
        assert validate_caldav_proxy_path("") is True

    def test_calendars_path_is_valid(self):
        """Standard calendars path should be valid."""
        assert validate_caldav_proxy_path("calendars/users/user@ex.com/uuid/") is True

    def test_principals_path_is_valid(self):
        """Standard principals path should be valid."""
        assert validate_caldav_proxy_path("principals/users/user@ex.com/") is True

    def test_traversal_is_rejected(self):
        """Directory traversal attempts should be rejected."""
        assert validate_caldav_proxy_path("calendars/../../etc/passwd") is False

    def test_null_byte_is_rejected(self):
        """Paths containing null bytes should be rejected."""
        assert validate_caldav_proxy_path("calendars/user\x00/") is False

    def test_unknown_prefix_is_rejected(self):
        """Paths without a known prefix should be rejected."""
        assert validate_caldav_proxy_path("etc/passwd") is False

    def test_leading_slash_calendars_is_valid(self):
        """Paths with leading slash should still be valid."""
        assert validate_caldav_proxy_path("/calendars/users/user@ex.com/uuid/") is True

    def test_internal_api_is_rejected(self):
        """Internal API paths should be explicitly blocked."""
        assert validate_caldav_proxy_path("internal-api/resources/") is False

    def test_internal_api_with_leading_slash_is_rejected(self):
        """Internal API paths with leading slash should be blocked."""
        assert validate_caldav_proxy_path("/internal-api/import/user/cal") is False

    def test_encoded_traversal_is_rejected(self):
        """URL-encoded directory traversal should be rejected."""
        assert validate_caldav_proxy_path("calendars/%2e%2e/%2e%2e/etc/passwd") is False

    def test_encoded_internal_api_is_rejected(self):
        """URL-encoded internal-api path should be blocked."""
        assert validate_caldav_proxy_path("%69nternal-api/resources/") is False

    def test_encoded_null_byte_is_rejected(self):
        """URL-encoded null byte should be rejected."""
        assert validate_caldav_proxy_path("calendars/user%00/") is False

    def test_double_encoded_traversal_is_rejected(self):
        """Double URL-encoded traversal (e.g. %252e%252e -> %2e%2e ->
        ..) must also be rejected.

        The validator unquotes until a fixed point is reached so an
        attacker cannot smuggle a `..` past the literal-substring check
        by stacking encoding layers.
        """
        assert validate_caldav_proxy_path("calendars/%252e%252e/etc/passwd") is False

    def test_triple_encoded_traversal_is_rejected(self):
        """Triple URL-encoded traversal should also be rejected."""
        assert (
            validate_caldav_proxy_path("calendars/%25252e%25252e/etc/passwd") is False
        )

    @pytest.mark.parametrize(
        "raw,description",
        [
            ("calendars/users/me/cal/\rfoo.ics", "CR"),
            ("calendars/users/me/cal/\nfoo.ics", "LF"),
            ("calendars/users/me/cal/\r\nX-Header: pwn", "CRLF header injection"),
            ("calendars/users/me/cal/\tfoo.ics", "tab"),
            ("calendars/users/me/cal/foo\x7f.ics", "DEL (0x7F)"),
            ("calendars/users/me/cal/foo\x01.ics", "SOH (0x01)"),
            ("calendars/users/me/cal/foo%0A.ics", "URL-encoded LF"),
            ("calendars/users/me/cal/foo%0d.ics", "URL-encoded CR (lowercase)"),
        ],
    )
    def test_control_characters_are_rejected(self, raw, description):
        """ASCII control bytes (CR/LF/tab/DEL/etc., raw or %-encoded) are
        rejected by the validator itself rather than relying on
        downstream libraries (urllib3 raises on CRLF in headers, but the
        validator is the documented gate). Also defends the debug logger
        against newline-injected log lines if a malformed path ever
        reached it before forwarding.
        """
        assert validate_caldav_proxy_path(raw) is False, (
            f"Expected control char ({description}) to be rejected"
        )


# ---------------------------------------------------------------------------
# Internal API test helpers
# ---------------------------------------------------------------------------

_intapi_http = CalDAVHTTPClient()
_INTAPI_HEADERS = {"X-LS-Internal-Api-Key": settings.CALDAV_INTERNAL_API_KEY}


@pytest.mark.django_db
@pytest.mark.xdist_group("caldav")
class TestInternalApiErrors:
    """InternalApiPlugin should reject invalid requests properly."""

    def test_internal_api_without_key_blocked(self):
        """Internal API requests without X-LS-Internal-Api-Key must be blocked.

        Note: the Django proxy blocks /internal-api/ paths, but we also test
        the CalDAV-level protection (defense in depth).
        """
        org = factories.OrganizationFactory(external_id="intapi-nokey")
        user = factories.UserFactory(email="user@intapi-nokey.com", organization=org)

        # Try via raw CalDAVHTTPClient without internal key
        resp = _intapi_http.request(
            "POST",
            user,
            "internal-api/calendars/",
            data=json.dumps(
                {
                    "email": "test@example.com",
                    "name": "Test",
                }
            ).encode("utf-8"),
            content_type="application/json",
            # No extra_headers with internal API key
        )
        assert resp.status_code in (401, 403), (
            f"Internal API without key should be blocked, got {resp.status_code}"
        )

    def test_internal_api_with_wrong_key_blocked(self):
        """Internal API with wrong key must be blocked."""
        org = factories.OrganizationFactory(external_id="intapi-badkey")
        user = factories.UserFactory(email="user@intapi-badkey.com", organization=org)

        resp = _intapi_http.request(
            "POST",
            user,
            "internal-api/calendars/",
            data=json.dumps(
                {
                    "email": "test@example.com",
                    "name": "Test",
                }
            ).encode("utf-8"),
            content_type="application/json",
            extra_headers={"X-LS-Internal-Api-Key": "wrong-key-12345"},
        )
        assert resp.status_code in (401, 403), (
            f"Internal API with wrong key should be blocked, got {resp.status_code}"
        )

    def test_create_calendar_missing_email(self):
        """POST /internal-api/calendars/ without email returns 400."""
        org = factories.OrganizationFactory(external_id="intapi-noemail")
        user = factories.UserFactory(email="user@intapi-noemail.com", organization=org)

        resp = _intapi_http.request(
            "POST",
            user,
            "internal-api/calendars/",
            data=json.dumps({"name": "Test"}).encode("utf-8"),
            content_type="application/json",
            extra_headers=_INTAPI_HEADERS,
        )
        assert resp.status_code == 400, (
            f"Missing email should return 400, got {resp.status_code}"
        )

    def test_mailbox_creates_under_mailboxes_namespace(self):
        """POST /internal-api/calendars/ with MAILBOX type must create
        the principal under principals/mailboxes/, not principals/users/.
        """
        org = factories.OrganizationFactory(external_id="intapi-ns")
        user = factories.UserFactory(email="user@intapi-ns.com", organization=org)
        target = "shared@intapi-ns.com"

        resp = _intapi_http.request(
            "POST",
            user,
            "internal-api/calendars/",
            data=json.dumps(
                {
                    "email": target,
                    "name": "Shared",
                    "calendar_user_type": "MAILBOX",
                    "org_id": str(user.organization_id),
                    "caller_email": user.email,
                }
            ).encode("utf-8"),
            content_type="application/json",
            extra_headers=_INTAPI_HEADERS,
        )
        assert resp.status_code in (200, 201), (
            f"Mailbox create failed: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert body["principal_uri"] == f"principals/mailboxes/{target}", (
            f"Expected principals/mailboxes/ namespace, got {body['principal_uri']}"
        )

    def test_individual_and_mailbox_coexist_for_same_email(self):
        """INDIVIDUAL and MAILBOX calendars for the same email must
        coexist — they live in separate principal namespaces.
        """
        org = factories.OrganizationFactory(external_id="intapi-coexist")
        user = factories.UserFactory(email="user@intapi-coexist.com", organization=org)
        target = "shared@intapi-coexist.com"

        # Create INDIVIDUAL calendar
        resp = _intapi_http.request(
            "POST",
            user,
            "internal-api/calendars/",
            data=json.dumps(
                {
                    "email": target,
                    "name": "Personal",
                    "calendar_user_type": "INDIVIDUAL",
                    "org_id": str(user.organization_id),
                }
            ).encode("utf-8"),
            content_type="application/json",
            extra_headers=_INTAPI_HEADERS,
        )
        assert resp.status_code in (200, 201), (
            f"Individual create failed: {resp.status_code} {resp.text}"
        )
        assert resp.json()["principal_uri"] == f"principals/users/{target}"

        # Create MAILBOX calendar for same email — separate namespace
        resp = _intapi_http.request(
            "POST",
            user,
            "internal-api/calendars/",
            data=json.dumps(
                {
                    "email": target,
                    "name": "Mailbox",
                    "calendar_user_type": "MAILBOX",
                    "org_id": str(user.organization_id),
                    "caller_email": user.email,
                }
            ).encode("utf-8"),
            content_type="application/json",
            extra_headers=_INTAPI_HEADERS,
        )
        assert resp.status_code in (200, 201), (
            f"Mailbox create for same email should succeed, "
            f"got {resp.status_code} {resp.text}"
        )
        assert resp.json()["principal_uri"] == f"principals/mailboxes/{target}"

    def test_sync_acls_malformed_json(self):
        """POST /internal-api/sync-mailbox-acls/ with bad JSON returns 400."""
        org = factories.OrganizationFactory(external_id="intapi-badjson")
        user = factories.UserFactory(email="user@intapi-badjson.com", organization=org)

        resp = _intapi_http.request(
            "POST",
            user,
            "internal-api/sync-mailbox-acls/",
            data=b"not json at all",
            content_type="application/json",
            extra_headers=_INTAPI_HEADERS,
        )
        assert resp.status_code == 400, (
            f"Malformed JSON should return 400, got {resp.status_code}"
        )

    def test_proxy_blocks_internal_api_path(self):
        """Django proxy must reject /caldav/internal-api/ requests."""
        org = factories.OrganizationFactory(external_id="intapi-proxy")
        user = factories.UserFactory(email="user@intapi-proxy.com", organization=org)
        client = APIClient()
        client.force_login(user)

        resp = client.generic(
            "POST",
            "/caldav/internal-api/calendars/",
            data=json.dumps({"email": "x@x.com"}).encode("utf-8"),
            content_type="application/json",
        )
        assert resp.status_code == 400, (
            f"Proxy should block internal-api paths, got {resp.status_code}"
        )


# ===================================================================
# Protocol-level unauthorized access
# ===================================================================
