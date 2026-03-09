"""Tests for the entitlements module."""

from unittest import mock

from django.conf import settings
from django.test import override_settings

import pytest
import requests
import responses
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_207_MULTI_STATUS,
    HTTP_403_FORBIDDEN,
)
from rest_framework.test import APIClient

from core import factories
from core.api.serializers import UserMeSerializer
from core.authentication.backends import OIDCAuthenticationBackend
from core.entitlements import EntitlementsUnavailableError, get_user_entitlements
from core.entitlements.backends.deploycenter import DeployCenterEntitlementsBackend
from core.entitlements.backends.local import LocalEntitlementsBackend
from core.entitlements.factory import get_entitlements_backend

# -- LocalEntitlementsBackend --


def test_local_backend_always_grants_access():
    """The local backend should always return can_access=True and can_admin=True."""
    backend = LocalEntitlementsBackend()
    result = backend.get_user_entitlements("sub-123", "user@example.com")
    assert result == {"can_access": True, "can_admin": True}


def test_local_backend_ignores_parameters():
    """The local backend should work regardless of parameters passed."""
    backend = LocalEntitlementsBackend()
    result = backend.get_user_entitlements(
        "sub-123",
        "user@example.com",
        user_info={"some": "claim"},
        force_refresh=True,
    )
    assert result == {"can_access": True, "can_admin": True}


# -- Factory --


@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_factory_returns_local_backend():
    """The factory should instantiate the configured backend."""
    get_entitlements_backend.cache_clear()
    backend = get_entitlements_backend()
    assert isinstance(backend, LocalEntitlementsBackend)
    get_entitlements_backend.cache_clear()


@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_factory_singleton():
    """The factory should return the same instance on repeated calls."""
    get_entitlements_backend.cache_clear()
    backend1 = get_entitlements_backend()
    backend2 = get_entitlements_backend()
    assert backend1 is backend2
    get_entitlements_backend.cache_clear()


# -- get_user_entitlements public API --


@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_get_user_entitlements_with_local_backend():
    """The public API should delegate to the configured backend."""
    get_entitlements_backend.cache_clear()
    result = get_user_entitlements("sub-123", "user@example.com")
    assert result["can_access"] is True
    get_entitlements_backend.cache_clear()


# -- DeployCenterEntitlementsBackend --

DC_URL = "https://deploy.example.com/api/v1.0/entitlements/"


@responses.activate
def test_deploycenter_backend_grants_access():
    """DeployCenter backend should return can_access from API response."""
    responses.add(
        responses.GET,
        DC_URL,
        json={"entitlements": {"can_access": True, "can_admin": True}},
        status=200,
    )

    backend = DeployCenterEntitlementsBackend(
        base_url=DC_URL,
        service_id="calendar",
        api_key="test-key",
    )
    result = backend.get_user_entitlements("sub-123", "user@example.com")
    assert result == {"can_access": True, "can_admin": True}

    # Verify request was made with correct params and header
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert "service_id=calendar" in request.url
    assert "account_email=user%40example.com" in request.url
    assert request.headers["X-Service-Auth"] == "Bearer test-key"


@responses.activate
def test_deploycenter_backend_denies_access():
    """DeployCenter backend should return can_access=False when API says so."""
    responses.add(
        responses.GET,
        DC_URL,
        json={"entitlements": {"can_access": False}},
        status=200,
    )

    backend = DeployCenterEntitlementsBackend(
        base_url=DC_URL,
        service_id="calendar",
        api_key="test-key",
    )
    result = backend.get_user_entitlements("sub-123", "user@example.com")
    assert result == {"can_access": False, "can_admin": False}


@responses.activate
@override_settings(ENTITLEMENTS_CACHE_TIMEOUT=300)
def test_deploycenter_backend_uses_cache():
    """DeployCenter should use cached results when not force_refresh."""
    responses.add(
        responses.GET,
        DC_URL,
        json={"entitlements": {"can_access": True}},
        status=200,
    )

    backend = DeployCenterEntitlementsBackend(
        base_url=DC_URL,
        service_id="calendar",
        api_key="test-key",
    )

    # First call hits the API
    result1 = backend.get_user_entitlements("sub-123", "user@example.com")
    assert result1["can_access"] is True
    assert len(responses.calls) == 1

    # Second call should use cache
    result2 = backend.get_user_entitlements("sub-123", "user@example.com")
    assert result2["can_access"] is True
    assert len(responses.calls) == 1  # No additional API call


@responses.activate
@override_settings(ENTITLEMENTS_CACHE_TIMEOUT=300)
def test_deploycenter_backend_force_refresh_bypasses_cache():
    """force_refresh=True should bypass cache and hit the API."""
    responses.add(
        responses.GET,
        DC_URL,
        json={"entitlements": {"can_access": True}},
        status=200,
    )
    responses.add(
        responses.GET,
        DC_URL,
        json={"entitlements": {"can_access": False}},
        status=200,
    )

    backend = DeployCenterEntitlementsBackend(
        base_url=DC_URL,
        service_id="calendar",
        api_key="test-key",
    )

    result1 = backend.get_user_entitlements("sub-123", "user@example.com")
    assert result1["can_access"] is True

    result2 = backend.get_user_entitlements(
        "sub-123", "user@example.com", force_refresh=True
    )
    assert result2["can_access"] is False
    assert len(responses.calls) == 2


@responses.activate
@override_settings(ENTITLEMENTS_CACHE_TIMEOUT=300)
def test_deploycenter_backend_fallback_to_stale_cache():
    """When API fails, should return stale cached value if available."""
    responses.add(
        responses.GET,
        DC_URL,
        json={"entitlements": {"can_access": True}},
        status=200,
    )

    backend = DeployCenterEntitlementsBackend(
        base_url=DC_URL,
        service_id="calendar",
        api_key="test-key",
    )

    # Populate cache
    backend.get_user_entitlements("sub-123", "user@example.com")

    # Now API fails
    responses.replace(
        responses.GET,
        DC_URL,
        body=requests.ConnectionError("Connection error"),
    )

    # force_refresh to hit API, but should fall back to cache
    result = backend.get_user_entitlements(
        "sub-123", "user@example.com", force_refresh=True
    )
    assert result["can_access"] is True


@responses.activate
def test_deploycenter_backend_raises_when_no_cache():
    """When API fails and no cache exists, should raise."""
    responses.add(
        responses.GET,
        DC_URL,
        body=requests.ConnectionError("Connection error"),
    )

    backend = DeployCenterEntitlementsBackend(
        base_url=DC_URL,
        service_id="calendar",
        api_key="test-key",
    )

    with pytest.raises(EntitlementsUnavailableError):
        backend.get_user_entitlements("sub-123", "user@example.com")


@responses.activate
def test_deploycenter_backend_sends_oidc_claims():
    """DeployCenter should forward configured OIDC claims."""
    responses.add(
        responses.GET,
        DC_URL,
        json={"entitlements": {"can_access": True}},
        status=200,
    )

    backend = DeployCenterEntitlementsBackend(
        base_url=DC_URL,
        service_id="calendar",
        api_key="test-key",
        oidc_claims=["organization"],
    )

    backend.get_user_entitlements(
        "sub-123",
        "user@example.com",
        user_info={"organization": "org-42", "other": "ignored"},
    )

    request = responses.calls[0].request
    assert "organization=org-42" in request.url
    assert "other" not in request.url


# -- Auth backend integration --


pytestmark = pytest.mark.django_db


def test_auth_backend_warms_cache_on_login():
    """post_get_or_create_user should call get_user_entitlements with force_refresh."""
    user = factories.UserFactory()
    backend = OIDCAuthenticationBackend()

    with mock.patch(
        "core.authentication.backends.get_user_entitlements",
        return_value={"can_access": True},
    ) as mock_ent:
        backend.post_get_or_create_user(user, {"sub": "x"}, is_new_user=False)
        mock_ent.assert_called_once_with(
            user_sub=user.sub,
            user_email=user.email,
            user_info={"sub": "x"},
            force_refresh=True,
        )


def test_auth_backend_login_succeeds_when_access_denied():
    """Login should succeed even when can_access is False (gated in frontend)."""
    user = factories.UserFactory()
    backend = OIDCAuthenticationBackend()

    with mock.patch(
        "core.authentication.backends.get_user_entitlements",
        return_value={"can_access": False},
    ):
        # Should not raise — user logs in, frontend gates access
        backend.post_get_or_create_user(user, {}, is_new_user=False)


def test_auth_backend_login_succeeds_when_entitlements_unavailable():
    """Login should succeed when entitlements service is unavailable."""
    user = factories.UserFactory()
    backend = OIDCAuthenticationBackend()

    with mock.patch(
        "core.authentication.backends.get_user_entitlements",
        side_effect=EntitlementsUnavailableError("unavailable"),
    ):
        # Should not raise
        backend.post_get_or_create_user(user, {}, is_new_user=False)


# -- UserMeSerializer (can_access field) --


def test_user_me_serializer_includes_can_access_true():
    """UserMeSerializer should include can_access=True when entitled."""
    user = factories.UserFactory()
    with mock.patch(
        "core.api.serializers.get_user_entitlements",
        return_value={"can_access": True},
    ):
        data = UserMeSerializer(user).data
    assert data["can_access"] is True


def test_user_me_serializer_includes_can_access_false():
    """UserMeSerializer should include can_access=False when not entitled."""
    user = factories.UserFactory()
    with mock.patch(
        "core.api.serializers.get_user_entitlements",
        return_value={"can_access": False},
    ):
        data = UserMeSerializer(user).data
    assert data["can_access"] is False


def test_user_me_serializer_can_access_fail_closed():
    """UserMeSerializer should return can_access=False when entitlements unavailable."""
    user = factories.UserFactory()
    with mock.patch(
        "core.api.serializers.get_user_entitlements",
        side_effect=EntitlementsUnavailableError("unavailable"),
    ):
        data = UserMeSerializer(user).data
    assert data["can_access"] is False


# -- Signals integration --


@pytest.mark.xdist_group("caldav")
@override_settings(
    CALDAV_URL="http://caldav:80",
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_signal_skips_calendar_when_not_entitled():
    """Calendar should NOT be created when entitlements deny access."""
    get_entitlements_backend.cache_clear()

    with (
        mock.patch(
            "core.signals.get_user_entitlements",
            return_value={"can_access": False},
        ) as mock_ent,
        mock.patch("core.signals.CalendarService") as mock_svc,
    ):
        factories.UserFactory()
        mock_ent.assert_called_once()
        mock_svc.assert_not_called()

    get_entitlements_backend.cache_clear()


@pytest.mark.xdist_group("caldav")
@override_settings(
    CALDAV_URL="http://caldav:80",
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_signal_skips_calendar_when_entitlements_unavailable():
    """Calendar should NOT be created when entitlements are unavailable (fail-closed)."""
    get_entitlements_backend.cache_clear()

    with (
        mock.patch(
            "core.signals.get_user_entitlements",
            side_effect=EntitlementsUnavailableError("unavailable"),
        ),
        mock.patch("core.signals.CalendarService") as mock_svc,
    ):
        factories.UserFactory()
        mock_svc.assert_not_called()

    get_entitlements_backend.cache_clear()


@pytest.mark.xdist_group("caldav")
@override_settings(
    CALDAV_URL="http://caldav:80",
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_signal_creates_calendar_when_entitled():
    """Calendar should be created when entitlements grant access."""
    get_entitlements_backend.cache_clear()

    with (
        mock.patch(
            "core.signals.get_user_entitlements",
            return_value={"can_access": True},
        ),
        mock.patch("core.signals.CalendarService") as mock_svc,
    ):
        factories.UserFactory()
        mock_svc.return_value.create_default_calendar.assert_called_once()

    get_entitlements_backend.cache_clear()


# -- CalDAV proxy entitlements enforcement --


@pytest.mark.django_db
class TestCalDAVProxyEntitlements:  # pylint: disable=no-member
    """Tests for entitlements enforcement in the CalDAV proxy."""

    @responses.activate
    def test_mkcalendar_blocked_when_not_entitled(self):
        """MKCALENDAR should return 403 when user has can_access=False."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        with mock.patch(
            "core.api.viewsets_caldav.get_user_entitlements",
            return_value={"can_access": False},
        ):
            response = client.generic(
                "MKCALENDAR",
                "/caldav/calendars/users/test@example.com/new-cal/",
            )

        assert response.status_code == HTTP_403_FORBIDDEN

    @responses.activate
    def test_mkcol_blocked_when_not_entitled(self):
        """MKCOL should return 403 when user has can_access=False."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        with mock.patch(
            "core.api.viewsets_caldav.get_user_entitlements",
            return_value={"can_access": False},
        ):
            response = client.generic(
                "MKCOL",
                "/caldav/calendars/users/test@example.com/new-cal/",
            )

        assert response.status_code == HTTP_403_FORBIDDEN

    @responses.activate
    def test_mkcalendar_blocked_when_entitlements_unavailable(self):
        """MKCALENDAR should return 403 when entitlements service
        is unavailable (fail-closed)."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        with mock.patch(
            "core.api.viewsets_caldav.get_user_entitlements",
            side_effect=EntitlementsUnavailableError("unavailable"),
        ):
            response = client.generic(
                "MKCALENDAR",
                "/caldav/calendars/users/test@example.com/new-cal/",
            )

        assert response.status_code == HTTP_403_FORBIDDEN

    @responses.activate
    def test_mkcalendar_allowed_when_entitled(self):
        """MKCALENDAR should be forwarded when user has can_access=True."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="MKCALENDAR",
                url=f"{caldav_url}/caldav/calendars/users/test@example.com/new-cal/",
                status=201,
                body="",
            )
        )

        with mock.patch(
            "core.api.viewsets_caldav.get_user_entitlements",
            return_value={"can_access": True},
        ):
            response = client.generic(
                "MKCALENDAR",
                "/caldav/calendars/users/test@example.com/new-cal/",
            )

        assert response.status_code == 201
        assert len(responses.calls) == 1

    @responses.activate
    def test_propfind_allowed_when_not_entitled(self):
        """PROPFIND should work for non-entitled users (shared calendars)."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

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

        # No entitlements mock needed — PROPFIND should not check entitlements
        response = client.generic("PROPFIND", "/caldav/")

        assert response.status_code == HTTP_207_MULTI_STATUS

    @responses.activate
    def test_report_allowed_when_not_entitled(self):
        """REPORT should work for non-entitled users (shared calendars)."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="REPORT",
                url=f"{caldav_url}/caldav/calendars/users/other@example.com/cal-id/",
                status=HTTP_207_MULTI_STATUS,
                body='<?xml version="1.0"?><multistatus xmlns="DAV:"></multistatus>',
                headers={"Content-Type": "application/xml"},
            )
        )

        response = client.generic(
            "REPORT",
            "/caldav/calendars/users/other@example.com/cal-id/",
        )

        assert response.status_code == HTTP_207_MULTI_STATUS

    @responses.activate
    def test_put_allowed_when_not_entitled(self):
        """PUT (event creation/update in shared calendar) should work
        for non-entitled users."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        caldav_url = settings.CALDAV_URL
        responses.add(
            responses.Response(
                method="PUT",
                url=f"{caldav_url}/caldav/calendars/users/other@example.com/cal-id/event.ics",
                status=HTTP_200_OK,
                body="",
            )
        )

        response = client.generic(
            "PUT",
            "/caldav/calendars/users/other@example.com/cal-id/event.ics",
            data=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
            content_type="text/calendar",
        )

        assert response.status_code == HTTP_200_OK


# -- import_events entitlements enforcement --


@pytest.mark.django_db
class TestImportEventsEntitlements:  # pylint: disable=no-member
    """Tests for entitlements enforcement on import_events endpoint."""

    def test_import_events_blocked_when_not_entitled(self):
        """import_events should return 403 when user has
        can_access=False."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        with mock.patch(
            "core.api.permissions.get_user_entitlements",
            return_value={"can_access": False},
        ):
            response = client.post(
                "/api/v1.0/calendars/import-events/",
                data={},
                format="multipart",
            )

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_import_events_blocked_when_entitlements_unavailable(self):
        """import_events should return 403 when entitlements service
        is unavailable (fail-closed)."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        with mock.patch(
            "core.api.permissions.get_user_entitlements",
            side_effect=EntitlementsUnavailableError("unavailable"),
        ):
            response = client.post(
                "/api/v1.0/calendars/import-events/",
                data={},
                format="multipart",
            )

        assert response.status_code == HTTP_403_FORBIDDEN

    def test_import_events_allowed_when_entitled(self):
        """import_events should proceed normally when user has
        can_access=True (will fail on validation, not entitlements)."""
        user = factories.UserFactory(email="test@example.com")
        client = APIClient()
        client.force_login(user)

        with mock.patch(
            "core.api.permissions.get_user_entitlements",
            return_value={"can_access": True},
        ):
            # No file or caldav_path — should fail with 400, not 403
            response = client.post(
                "/api/v1.0/calendars/import-events/",
                data={},
                format="multipart",
            )

        # Should pass entitlements check but fail on missing caldav_path
        assert response.status_code == 400
