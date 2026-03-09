"""Tests for CalDAV proxy view."""

# pylint: disable=no-member

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

from core import factories
from core.services.caldav_service import validate_caldav_proxy_path


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
        """Test that proxy forwards X-Forwarded-User headers."""
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

        # Verify headers were forwarded
        assert request.headers["X-Forwarded-User"] == user.email
        assert request.headers["X-Forwarded-Host"] is not None
        assert request.headers["X-Forwarded-Proto"] == "http"

    @responses.activate
    def test_proxy_ignores_client_sent_x_forwarded_user_header(self):
        """Test that proxy ignores and overwrites any X-Forwarded-User header sent by client.

        This is a security test to ensure that hostile clients cannot impersonate other users
        by sending a malicious X-Forwarded-User header. The proxy should always use the
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

        # Try to send a malicious X-Forwarded-User header as if we were another user
        malicious_email = "attacker@example.com"
        client.generic(
            "PROPFIND",
            "/caldav/",
            HTTP_X_FORWARDED_USER=malicious_email,
        )

        # Verify request was made to CalDAV server
        assert len(responses.calls) == 1
        request = responses.calls[0].request

        # Verify that the X-Forwarded-User header uses the authenticated user's email,
        # NOT the malicious header value sent by the client
        assert request.headers["X-Forwarded-User"] == user.email, (
            f"Expected X-Forwarded-User to be {user.email} (authenticated user), "
            f"but got {request.headers.get('X-Forwarded-User')}. "
            f"This indicates a security vulnerability - client-sent headers are being trusted!"
        )
        assert request.headers["X-Forwarded-User"] != malicious_email, (
            "X-Forwarded-User should NOT use client-sent header value"
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

        # Verify all URLs that start with /principals/ or /calendars/ include the proxy prefix
        # This verifies that sabre/dav's BaseUriPlugin is working correctly
        for href_elem in href_elems:
            href = href_elem.text
            if href and (
                href.startswith("/principals/") or href.startswith("/calendars/")
            ):
                assert href.startswith("/caldav/"), (
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
        """POST to outbox should include X-Forwarded-User and X-Api-Key."""
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
        assert forwarded.headers["X-Forwarded-User"] == user.email
        assert forwarded.headers["X-Api-Key"] == settings.CALDAV_OUTBOUND_API_KEY

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
        """POST to outbox should include X-CalDAV-Organization header."""
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
        assert forwarded.headers["X-CalDAV-Organization"] == str(user.organization_id)


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
