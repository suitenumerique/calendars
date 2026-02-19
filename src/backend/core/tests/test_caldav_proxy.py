"""Tests for CalDAV proxy view."""

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
        response = client.generic("PROPFIND", "/api/v1.0/caldav/")
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

        response = client.generic("PROPFIND", "/api/v1.0/caldav/")

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
                url=f"{caldav_url}/api/v1.0/caldav/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        # Try to send a malicious X-Forwarded-User header as if we were another user
        malicious_email = "attacker@example.com"
        response = client.generic(
            "PROPFIND",
            "/api/v1.0/caldav/",
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

    @pytest.mark.skipif(
        not settings.CALDAV_URL,
        reason="CalDAV server URL not configured - integration test requires real server",
    )
    def test_proxy_propfind_response_contains_prefixed_urls(self):
        """Integration test: PROPFIND responses from sabre/dav should contain URLs with proxy prefix.

        This test verifies that sabre/dav's BaseUriPlugin correctly uses X-Forwarded-Prefix
        to generate URLs with the proxy prefix. It requires the CalDAV server to be running.
        Note: This test does NOT use @responses.activate as it needs to hit the real server.
        """
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        # Make actual request to CalDAV server through proxy
        # The server should use X-Forwarded-Prefix to generate URLs
        propfind_body = '<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>'
        response = client.generic(
            "PROPFIND",
            "/api/v1.0/caldav/",
            data=propfind_body,
            content_type="application/xml",
        )

        assert response.status_code == HTTP_207_MULTI_STATUS, (
            f"Expected 207 Multi-Status, got {response.status_code}: {response.content.decode('utf-8', errors='ignore')}"
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
                assert href.startswith("/api/v1.0/caldav/"), (
                    f"Expected URL to start with /api/v1.0/caldav/, got {href}. "
                    f"This indicates sabre/dav BaseUriPlugin is not using X-Forwarded-Prefix correctly. "
                    f"Full response: {response.content.decode('utf-8', errors='ignore')}"
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
                <href>/api/v1.0/caldav/calendars/test@example.com/calendar-id/</href>
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
                url=f"{caldav_url}/api/v1.0/caldav/",
                status=HTTP_207_MULTI_STATUS,
                body=propfind_xml,
                headers={"Content-Type": "application/xml"},
            )
        )

        response = client.generic("PROPFIND", "/api/v1.0/caldav/")

        assert response.status_code == HTTP_207_MULTI_STATUS

        # Parse the response XML
        root = ET.fromstring(response.content)

        # Find the href element
        href_elem = root.find(".//{DAV:}href")
        assert href_elem is not None

        # Verify the URL is passed through unchanged (sabre/dav should generate it with prefix)
        href = href_elem.text
        assert href == "/api/v1.0/caldav/calendars/test@example.com/calendar-id/", (
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
                <D:href>/api/v1.0/caldav/principals/test@example.com/</D:href>
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
                url=f"{caldav_url}/api/v1.0/caldav/",
                status=HTTP_207_MULTI_STATUS,
                body=propfind_xml,
                headers={"Content-Type": "application/xml"},
            )
        )

        response = client.generic("PROPFIND", "/api/v1.0/caldav/")

        assert response.status_code == HTTP_207_MULTI_STATUS

        # Parse the response XML
        root = ET.fromstring(response.content)

        # Find the D:href element (namespaced)
        href_elem = root.find(".//{DAV:}href")
        assert href_elem is not None

        # Verify the URL is passed through unchanged (sabre/dav should generate it with prefix)
        href = href_elem.text
        assert href == "/api/v1.0/caldav/principals/test@example.com/", (
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
                url=f"{caldav_url}/api/v1.0/caldav/principals/test@example.com/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        # Request a specific path
        response = client.generic(
            "PROPFIND", "/api/v1.0/caldav/principals/test@example.com/"
        )

        # Verify the request was made to the correct URL
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert (
            request.url == f"{caldav_url}/api/v1.0/caldav/principals/test@example.com/"
        )

    @responses.activate
    def test_proxy_handles_options_request(self):
        """Test that OPTIONS requests are handled for CORS."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        response = client.options("/api/v1.0/caldav/")

        assert response.status_code == HTTP_200_OK
        assert "Access-Control-Allow-Methods" in response
        assert "PROPFIND" in response["Access-Control-Allow-Methods"]

    def test_proxy_rejects_path_traversal(self):
        """Test that proxy rejects paths with directory traversal."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        response = client.generic(
            "PROPFIND", "/api/v1.0/caldav/calendars/../../etc/passwd"
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    def test_proxy_rejects_non_caldav_path(self):
        """Test that proxy rejects paths outside allowed prefixes."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        response = client.generic("PROPFIND", "/api/v1.0/caldav/etc/passwd")
        assert response.status_code == HTTP_400_BAD_REQUEST


class TestValidateCaldavProxyPath:
    """Tests for validate_caldav_proxy_path utility."""

    def test_empty_path_is_valid(self):
        assert validate_caldav_proxy_path("") is True

    def test_calendars_path_is_valid(self):
        assert validate_caldav_proxy_path("calendars/user@ex.com/uuid/") is True

    def test_principals_path_is_valid(self):
        assert validate_caldav_proxy_path("principals/user@ex.com/") is True

    def test_traversal_is_rejected(self):
        assert validate_caldav_proxy_path("calendars/../../etc/passwd") is False

    def test_null_byte_is_rejected(self):
        assert validate_caldav_proxy_path("calendars/user\x00/") is False

    def test_unknown_prefix_is_rejected(self):
        assert validate_caldav_proxy_path("etc/passwd") is False

    def test_leading_slash_calendars_is_valid(self):
        assert validate_caldav_proxy_path("/calendars/user@ex.com/uuid/") is True
