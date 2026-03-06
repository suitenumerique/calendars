"""Tests for permissions, access control, and security edge cases."""

from unittest import mock

from django.conf import settings
from django.test import override_settings

import pytest
import responses
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_207_MULTI_STATUS,
    HTTP_403_FORBIDDEN,
)
from rest_framework.test import APIClient

from core import factories
from core.entitlements import EntitlementsUnavailableError
from core.entitlements.factory import get_entitlements_backend
from core.services.caldav_service import (
    CALDAV_PATH_PATTERN,
    normalize_caldav_path,
    verify_caldav_access,
)

# ---------------------------------------------------------------------------
# verify_caldav_access — resource paths
# ---------------------------------------------------------------------------


class TestVerifyCaldavAccessResourcePaths:
    """Tests for verify_caldav_access() with resource calendar paths."""

    def _make_user(self, email="alice@example.com", org_id=None):
        """Create a mock user object."""
        user = mock.Mock()
        user.email = email
        user.organization_id = org_id
        return user

    def test_resource_path_allowed_when_user_has_org(self):
        """Users with an organization can access resource calendars."""
        user = self._make_user(org_id="some-org-uuid")
        path = "/calendars/resources/abc-123/default/"
        assert verify_caldav_access(user, path) is True

    def test_resource_path_denied_when_user_has_no_org(self):
        """Users without an organization cannot access resource calendars."""
        user = self._make_user(org_id=None)
        path = "/calendars/resources/abc-123/default/"
        assert verify_caldav_access(user, path) is False

    def test_user_path_allowed_for_own_email(self):
        """Users can access their own calendar paths."""
        user = self._make_user(email="alice@example.com")
        path = "/calendars/users/alice@example.com/cal-uuid/"
        assert verify_caldav_access(user, path) is True

    def test_user_path_denied_for_other_email(self):
        """Users cannot access another user's calendar path."""
        user = self._make_user(email="alice@example.com")
        path = "/calendars/users/bob@example.com/cal-uuid/"
        assert verify_caldav_access(user, path) is False

    def test_invalid_path_denied(self):
        """Paths that don't match the expected pattern are rejected."""
        user = self._make_user(org_id="some-org")
        assert verify_caldav_access(user, "/etc/passwd") is False
        assert verify_caldav_access(user, "/calendars/") is False
        assert verify_caldav_access(user, "/calendars/unknown/x/y/") is False

    def test_path_traversal_denied(self):
        """Path traversal attempts are rejected."""
        user = self._make_user(email="alice@example.com")
        path = "/calendars/users/alice@example.com/../../../etc/passwd/"
        assert verify_caldav_access(user, path) is False

    def test_resource_path_pattern_matches(self):
        """The CALDAV_PATH_PATTERN regex matches resource paths."""
        assert CALDAV_PATH_PATTERN.match("/calendars/resources/abc-123/default/")
        assert CALDAV_PATH_PATTERN.match(
            "/calendars/resources/a1b2c3d4-e5f6-7890-abcd-ef1234567890/default/"
        )

    def test_user_path_case_insensitive(self):
        """Email comparison in user paths should be case-insensitive."""
        user = self._make_user(email="Alice@Example.COM")
        path = "/calendars/users/alice@example.com/cal-uuid/"
        assert verify_caldav_access(user, path) is True


# ---------------------------------------------------------------------------
# IsOrgAdmin permission
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIsOrgAdminPermission:
    """Tests for the IsOrgAdmin permission class on the ResourceViewSet."""

    @override_settings(
        ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
        ENTITLEMENTS_BACKEND_PARAMETERS={},
    )
    def test_admin_user_can_create_resource(self):
        """Users with can_admin=True can create resources."""
        get_entitlements_backend.cache_clear()
        org = factories.OrganizationFactory(external_id="test-org")
        admin = factories.UserFactory(organization=org)

        client = APIClient()
        client.force_authenticate(user=admin)

        with mock.patch(
            "core.services.caldav_service.requests.request"
        ) as mock_request:
            mock_response = mock.Mock()
            mock_response.status_code = 201
            mock_response.text = '{"principal_uri": "principals/resources/x"}'
            mock_request.return_value = mock_response

            response = client.post(
                "/api/v1.0/resources/",
                {"name": "Room 1"},
                format="json",
            )

        assert response.status_code == HTTP_201_CREATED
        get_entitlements_backend.cache_clear()

    def test_non_admin_user_denied_resource_creation(self):
        """Users with can_admin=False are denied by IsOrgAdmin."""
        org = factories.OrganizationFactory(external_id="test-org")
        user = factories.UserFactory(organization=org)

        client = APIClient()
        client.force_authenticate(user=user)

        # Patch where IsOrgAdmin actually looks up get_user_entitlements
        with mock.patch(
            "core.api.permissions.get_user_entitlements",
            return_value={"can_access": True, "can_admin": False},
        ):
            response = client.post(
                "/api/v1.0/resources/",
                {"name": "Room 1"},
                format="json",
            )

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_entitlements_unavailable_denies_access(self):
        """IsOrgAdmin is fail-closed: denies when entitlements service is down."""
        org = factories.OrganizationFactory(external_id="test-org")
        user = factories.UserFactory(organization=org)

        client = APIClient()
        client.force_authenticate(user=user)

        with mock.patch(
            "core.api.permissions.get_user_entitlements",
            side_effect=EntitlementsUnavailableError("Service unavailable"),
        ):
            response = client.post(
                "/api/v1.0/resources/",
                {"name": "Room 1"},
                format="json",
            )

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_unauthenticated_user_denied(self):
        """Unauthenticated users are denied by IsOrgAdmin (inherits IsAuthenticated)."""
        client = APIClient()
        response = client.post(
            "/api/v1.0/resources/",
            {"name": "Room 1"},
            format="json",
        )
        # 401 or 403 depending on DRF config
        assert response.status_code in (401, 403)

    def test_non_admin_user_denied_resource_deletion(self):
        """Users with can_admin=False cannot delete resources either."""
        org = factories.OrganizationFactory(external_id="test-org")
        user = factories.UserFactory(organization=org)

        client = APIClient()
        client.force_authenticate(user=user)

        with mock.patch(
            "core.api.permissions.get_user_entitlements",
            return_value={"can_access": True, "can_admin": False},
        ):
            response = client.delete("/api/v1.0/resources/some-uuid/")

        assert response.status_code == HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# CalDAV proxy — X-CalDAV-Organization header forwarding
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCalDAVProxyOrgHeader:
    """Tests that the CalDAV proxy forwards the org header correctly."""

    @responses.activate
    def test_proxy_sends_org_header(self):
        """CalDAV proxy sends X-CalDAV-Organization for users with an org."""
        org = factories.OrganizationFactory(external_id="org-alpha")
        user = factories.UserFactory(email="alice@example.com", organization=org)

        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="PROPFIND",
                url=f"{caldav_url}/caldav/principals/resources/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        client.generic("PROPFIND", "/caldav/principals/resources/")

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request.headers["X-CalDAV-Organization"] == str(org.id)

    @responses.activate
    def test_proxy_omits_org_header_when_no_org(self):
        """CalDAV proxy omits X-CalDAV-Organization for users without an org."""
        user = factories.UserFactory(email="alice@example.com", organization=None)

        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="PROPFIND",
                url=f"{caldav_url}/caldav/principals/resources/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        client.generic("PROPFIND", "/caldav/principals/resources/")

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert "X-CalDAV-Organization" not in request.headers

    @responses.activate
    def test_proxy_cannot_spoof_org_header(self):
        """Client-sent X-CalDAV-Organization is overwritten by the proxy."""
        org = factories.OrganizationFactory(external_id="real-org")
        user = factories.UserFactory(email="alice@example.com", organization=org)

        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="PROPFIND",
                url=f"{caldav_url}/caldav/principals/resources/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        # Attempt to spoof the org header
        client.generic(
            "PROPFIND",
            "/caldav/principals/resources/",
            HTTP_X_CALDAV_ORGANIZATION="spoofed-org-id",
        )

        assert len(responses.calls) == 1
        request = responses.calls[0].request
        # The proxy should use the user's real org ID, not the spoofed one
        assert request.headers["X-CalDAV-Organization"] == str(org.id)
        assert request.headers["X-CalDAV-Organization"] != "spoofed-org-id"


# ---------------------------------------------------------------------------
# IsEntitled permission — fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIsEntitledFailClosed:
    """Tests that IsEntitled permission is fail-closed."""

    def test_import_denied_when_entitlements_unavailable(self):
        """ICS import should be denied when entitlements service is down."""
        user = factories.UserFactory(email="alice@example.com")

        client = APIClient()
        client.force_authenticate(user=user)

        with mock.patch(
            "core.api.permissions.get_user_entitlements",
            side_effect=EntitlementsUnavailableError("Service unavailable"),
        ):
            response = client.post(
                "/api/v1.0/calendars/import-events/",
                format="multipart",
            )

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_import_denied_when_can_access_false(self):
        """ICS import should be denied when can_access=False."""
        user = factories.UserFactory(email="alice@example.com")

        client = APIClient()
        client.force_authenticate(user=user)

        with mock.patch(
            "core.api.permissions.get_user_entitlements",
            return_value={"can_access": False, "can_admin": False},
        ):
            response = client.post(
                "/api/v1.0/calendars/import-events/",
                format="multipart",
            )

        assert response.status_code == HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# normalize_caldav_path
# ---------------------------------------------------------------------------


class TestNormalizeCaldavPath:
    """Tests for normalize_caldav_path helper."""

    def test_strips_old_api_prefix(self):
        """Should strip any prefix before /calendars/."""
        result = normalize_caldav_path(
            "/api/v1.0/caldav/calendars/users/user@ex.com/uuid/"
        )
        assert result == "/calendars/users/user@ex.com/uuid/"

    def test_strips_new_prefix(self):
        """Should strip /caldav prefix."""
        result = normalize_caldav_path("/caldav/calendars/users/user@ex.com/uuid/")
        assert result == "/calendars/users/user@ex.com/uuid/"

    def test_adds_leading_slash(self):
        """Should add a leading slash if missing."""
        result = normalize_caldav_path("calendars/users/user@ex.com/uuid/")
        assert result == "/calendars/users/user@ex.com/uuid/"

    def test_adds_trailing_slash(self):
        """Should add a trailing slash if missing."""
        result = normalize_caldav_path("/calendars/users/user@ex.com/uuid")
        assert result == "/calendars/users/user@ex.com/uuid/"

    def test_resource_path_unchanged(self):
        """Resource paths should pass through unchanged."""
        result = normalize_caldav_path("/calendars/resources/abc-123/default/")
        assert result == "/calendars/resources/abc-123/default/"
