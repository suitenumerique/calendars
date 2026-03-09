"""Tests for the organizations feature."""

from django.test import override_settings

import pytest
from rest_framework.status import HTTP_200_OK
from rest_framework.test import APIClient

from core import factories
from core.authentication.backends import resolve_organization
from core.entitlements.factory import get_entitlements_backend
from core.models import Organization

# -- Organization model --


@pytest.mark.django_db
def test_organization_str_with_name():
    """Organization.__str__ returns the name when set."""
    org = factories.OrganizationFactory(name="Acme Corp", external_id="acme")
    assert str(org) == "Acme Corp"


@pytest.mark.django_db
def test_organization_str_without_name():
    """Organization.__str__ falls back to external_id when name is empty."""
    org = factories.OrganizationFactory(name="", external_id="acme")
    assert str(org) == "acme"


@pytest.mark.django_db
def test_organization_unique_external_id():
    """external_id must be unique."""
    factories.OrganizationFactory(external_id="org-1")
    with pytest.raises(Exception):  # noqa: B017
        factories.OrganizationFactory(external_id="org-1")


# -- Org resolution on login --


@pytest.mark.django_db
def test_resolve_org_from_email_domain():
    """Without OIDC_USERINFO_ORGANIZATION_CLAIM, org is derived from email domain."""
    user = factories.UserFactory(email="alice@ministry.gouv.fr")

    resolve_organization(user, claims={}, entitlements={})

    user.refresh_from_db()
    assert user.organization is not None
    assert user.organization.external_id == "ministry.gouv.fr"
    assert user.organization.name == "ministry.gouv.fr"


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="siret")
def test_resolve_org_from_oidc_claim():
    """With OIDC_USERINFO_ORGANIZATION_CLAIM, org is derived from the claim."""
    user = factories.UserFactory(email="alice@ministry.gouv.fr")

    resolve_organization(
        user,
        claims={"siret": "13002526500013"},
        entitlements={"organization_name": "Ministere X"},
    )

    user.refresh_from_db()
    assert user.organization is not None
    assert user.organization.external_id == "13002526500013"
    assert user.organization.name == "Ministere X"


@pytest.mark.django_db
def test_resolve_org_updates_name():
    """Org name is updated from entitlements on subsequent logins."""
    org = factories.OrganizationFactory(external_id="example.com", name="Old Name")
    user = factories.UserFactory(email="alice@example.com", organization=org)

    resolve_organization(
        user,
        claims={},
        entitlements={"organization_name": "New Name"},
    )

    org.refresh_from_db()
    assert org.name == "New Name"


@pytest.mark.django_db
def test_resolve_org_reuses_existing():
    """Existing org is reused, not duplicated."""
    org = factories.OrganizationFactory(external_id="example.com")
    user = factories.UserFactory(email="bob@example.com")

    resolve_organization(user, claims={}, entitlements={})

    user.refresh_from_db()
    assert user.organization_id == org.id
    assert Organization.objects.filter(external_id="example.com").count() == 1


# -- User API: /users/me/ --


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_users_me_includes_organization():
    """GET /users/me/ includes the user's organization."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(name="Test Org", external_id="test")
    user = factories.UserFactory(organization=org)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/v1.0/users/me/")

    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert data["organization"]["id"] == str(org.id)
    assert data["organization"]["name"] == "Test Org"
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_users_me_includes_can_admin():
    """GET /users/me/ includes can_admin from entitlements."""
    get_entitlements_backend.cache_clear()
    user = factories.UserFactory()

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/v1.0/users/me/")

    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert "can_admin" in data
    # Local backend returns True for can_admin
    assert data["can_admin"] is True
    get_entitlements_backend.cache_clear()


# -- User list scoping --


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_user_list_scoped_by_org():
    """User list only returns users from the same org."""
    get_entitlements_backend.cache_clear()
    org_a = factories.OrganizationFactory(external_id="org-a")
    org_b = factories.OrganizationFactory(external_id="org-b")

    alice = factories.UserFactory(email="alice@example.com", organization=org_a)
    factories.UserFactory(email="bob@other.com", organization=org_b)

    client = APIClient()
    client.force_authenticate(user=alice)
    response = client.get("/api/v1.0/users/?q=bob@other.com")

    assert response.status_code == HTTP_200_OK
    # Bob should NOT be visible (different org)
    assert len(response.json()["results"]) == 0
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_user_list_same_org_visible():
    """User list returns users from the same org."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(external_id="org-a")
    alice = factories.UserFactory(email="alice@example.com", organization=org)
    factories.UserFactory(email="carol@example.com", organization=org)

    client = APIClient()
    client.force_authenticate(user=alice)
    response = client.get("/api/v1.0/users/?q=carol@example.com")

    assert response.status_code == HTTP_200_OK
    data = response.json()["results"]
    assert len(data) == 1
    assert data[0]["email"] == "carol@example.com"
    get_entitlements_backend.cache_clear()


# -- Sharing level --


@pytest.mark.django_db
def test_effective_sharing_level_defaults_to_server_setting():
    """Organization without override returns server-wide default."""
    org = factories.OrganizationFactory(default_sharing_level=None)
    assert org.effective_sharing_level == "freebusy"


@pytest.mark.django_db
@override_settings(ORG_DEFAULT_SHARING_LEVEL="none")
def test_effective_sharing_level_follows_server_override():
    """Organization without override returns overridden server default."""
    org = factories.OrganizationFactory(default_sharing_level=None)
    assert org.effective_sharing_level == "none"


@pytest.mark.django_db
def test_effective_sharing_level_org_override():
    """Organization with explicit level ignores server default."""
    org = factories.OrganizationFactory(default_sharing_level="read")
    assert org.effective_sharing_level == "read"


# -- Organization settings API --


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_org_settings_retrieve():
    """GET /organization-settings/current/ returns org sharing level."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(external_id="test-org")
    user = factories.UserFactory(organization=org)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/v1.0/organization-settings/current/")

    assert response.status_code == HTTP_200_OK
    assert response.json()["sharing_level"] == "freebusy"
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_org_settings_update_sharing_level():
    """PATCH /organization-settings/current/ updates sharing level."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(external_id="test-org")
    user = factories.UserFactory(organization=org)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.patch(
        "/api/v1.0/organization-settings/current/",
        {"default_sharing_level": "none"},
        format="json",
    )

    assert response.status_code == HTTP_200_OK
    org.refresh_from_db()
    assert org.default_sharing_level == "none"
    assert response.json()["sharing_level"] == "none"
    get_entitlements_backend.cache_clear()


@pytest.mark.django_db
@override_settings(
    ENTITLEMENTS_BACKEND="core.entitlements.backends.local.LocalEntitlementsBackend",
    ENTITLEMENTS_BACKEND_PARAMETERS={},
)
def test_org_settings_update_rejects_invalid_level():
    """PATCH with invalid sharing level returns 400."""
    get_entitlements_backend.cache_clear()
    org = factories.OrganizationFactory(external_id="test-org")
    user = factories.UserFactory(organization=org)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.patch(
        "/api/v1.0/organization-settings/current/",
        {"default_sharing_level": "superadmin"},
        format="json",
    )

    assert response.status_code == 400
    get_entitlements_backend.cache_clear()
