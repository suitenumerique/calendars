"""Tests for the resource provisioning API."""

import json
from unittest import mock

from django.test import override_settings

import pytest
from rest_framework.status import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
)
from rest_framework.test import APIClient

from core import factories
from core.entitlements.factory import get_entitlements_backend

# -- Permission checks --


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_create_resource_requires_auth():
    """POST /resources/ requires authentication."""
    get_entitlements_backend.cache_clear()
    client = APIClient()
    response = client.post(
        "/api/v1.0/resources/",
        {"name": "Room 1"},
        format="json",
    )
    assert response.status_code == HTTP_401_UNAUTHORIZED
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_create_resource_success():
    """POST /resources/ creates a resource principal via the internal API."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(external_id="test-org")
    admin = factories.UserFactory(organization=org)

    client = APIClient()
    client.force_authenticate(user=admin)

    with mock.patch("core.services.caldav_service.requests.request") as mock_request:
        # Mock the internal API response for resource creation
        mock_response = mock.Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "principal_uri": "principals/resources/some-uuid",
            "email": "c_test@resource.calendar.localhost",
        }
        mock_response.text = '{"principal_uri": "principals/resources/some-uuid"}'
        mock_request.return_value = mock_response

        response = client.post(
            "/api/v1.0/resources/",
            {"name": "Room 101", "resource_type": "ROOM"},
            format="json",
        )

    assert response.status_code == HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Room 101"
    assert data["resource_type"] == "ROOM"
    assert "email" in data
    assert "id" in data
    # Principal URI uses the opaque UUID, not the slug
    assert data["principal_uri"].startswith("principals/resources/")
    assert data["principal_uri"] == f"principals/resources/{data['id']}"

    # Verify the HTTP call went to the internal API
    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    url = call_kwargs.kwargs.get("url", "") or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else ""
    )
    headers = call_kwargs.kwargs.get("headers", {})
    assert "internal-api/resources" in url
    assert "X-Internal-Api-Key" in headers

    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_delete_resource():
    """DELETE /resources/{resource_id}/ deletes the resource via internal API."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(external_id="test-org")
    admin = factories.UserFactory(organization=org)

    client = APIClient()
    client.force_authenticate(user=admin)

    resource_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    with mock.patch("core.services.caldav_service.requests.request") as mock_request:
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"deleted": True}
        mock_response.text = '{"deleted": true}'
        mock_request.return_value = mock_response

        response = client.delete(f"/api/v1.0/resources/{resource_id}/")

    assert response.status_code == HTTP_204_NO_CONTENT

    # Verify the HTTP call went to the internal API
    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    url = call_kwargs.kwargs.get("url", "") or (
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else ""
    )
    headers = call_kwargs.kwargs.get("headers", {})
    assert f"internal-api/resources/{resource_id}" in url
    assert "X-Internal-Api-Key" in headers

    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_delete_resource_cross_org_blocked():
    """Cannot delete a resource from another organization."""
    get_entitlements_backend.cache_clear()
    org_a = factories.OrganizationFactory(external_id="org-a")
    admin = factories.UserFactory(organization=org_a)

    client = APIClient()
    client.force_authenticate(user=admin)

    with mock.patch("core.services.caldav_service.requests.request") as mock_request:
        mock_response = mock.Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": "Cannot delete a resource from a different organization."
        }
        mock_response.text = (
            '{"error": "Cannot delete a resource from a different organization."}'
        )
        mock_request.return_value = mock_response

        response = client.delete(
            "/api/v1.0/resources/b1b2c3d4-e5f6-7890-abcd-ef1234567890/"
        )

    assert response.status_code == HTTP_400_BAD_REQUEST
    assert "different organization" in response.json()["detail"]

    get_entitlements_backend.cache_clear()


# -- Lateral access tests --


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_create_resource_sends_user_org_id():
    """Create resource always sends the authenticated user's org_id, not a caller-supplied one."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(external_id="org-alpha")
    admin = factories.UserFactory(organization=org)

    client = APIClient()
    client.force_authenticate(user=admin)

    with mock.patch("core.services.caldav_service.requests.request") as mock_request:
        mock_response = mock.Mock()
        mock_response.status_code = 201
        mock_response.text = '{"principal_uri": "principals/resources/x"}'
        mock_request.return_value = mock_response

        client.post(
            "/api/v1.0/resources/",
            {"name": "Room 1"},
            format="json",
        )

    # Verify the JSON body sent to internal API contains the user's org
    call_kwargs = mock_request.call_args
    body = json.loads(call_kwargs.kwargs.get("data", b"{}"))
    assert body["org_id"] == str(org.id)

    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_delete_resource_sends_user_org_id():
    """Delete resource sends the authenticated user's org_id in the header."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(external_id="org-beta")
    admin = factories.UserFactory(organization=org)

    client = APIClient()
    client.force_authenticate(user=admin)

    resource_id = "a1b2c3d4-0000-0000-0000-000000000001"

    with mock.patch("core.services.caldav_service.requests.request") as mock_request:
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.text = '{"deleted": true}'
        mock_request.return_value = mock_response

        client.delete(f"/api/v1.0/resources/{resource_id}/")

    call_kwargs = mock_request.call_args
    headers = call_kwargs.kwargs.get("headers", {})
    assert headers.get("X-CalDAV-Organization") == str(org.id)

    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_create_resource_without_org_sends_null_org():
    """A user without an org sends null org_id — SabreDAV will store it as NULL."""
    get_entitlements_backend.cache_clear()
    admin = factories.UserFactory(organization=None)

    client = APIClient()
    client.force_authenticate(user=admin)

    with mock.patch("core.services.caldav_service.requests.request") as mock_request:
        mock_response = mock.Mock()
        mock_response.status_code = 201
        mock_response.text = '{"principal_uri": "principals/resources/x"}'
        mock_request.return_value = mock_response

        client.post(
            "/api/v1.0/resources/",
            {"name": "Orphan Room"},
            format="json",
        )

    call_kwargs = mock_request.call_args
    body = json.loads(call_kwargs.kwargs.get("data", b"{}"))
    assert body["org_id"] is None

    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_delete_resource_without_org_blocked():
    """A user without an org cannot delete resources (SabreDAV returns 403)."""
    get_entitlements_backend.cache_clear()
    admin = factories.UserFactory(organization=None)

    client = APIClient()
    client.force_authenticate(user=admin)

    resource_id = "a1b2c3d4-0000-0000-0000-000000000002"

    with mock.patch("core.services.caldav_service.requests.request") as mock_request:
        mock_response = mock.Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": "Cannot delete a resource from a different organization"
        }
        mock_response.text = (
            '{"error": "Cannot delete a resource from a different organization"}'
        )
        mock_request.return_value = mock_response

        response = client.delete(f"/api/v1.0/resources/{resource_id}/")

    # Verify no org header was sent (user has no org)
    call_kwargs = mock_request.call_args
    headers = call_kwargs.kwargs.get("headers", {})
    assert "X-CalDAV-Organization" not in headers

    assert response.status_code == HTTP_400_BAD_REQUEST

    get_entitlements_backend.cache_clear()
