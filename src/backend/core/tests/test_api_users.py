"""
Test users API endpoints in the calendars core app.
"""

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.api import serializers

pytestmark = pytest.mark.django_db


def test_api_users_list_anonymous():
    """Anonymous users should not be allowed to list users."""
    factories.UserFactory()
    client = APIClient()
    response = client.get("/api/v1.0/users/")
    assert response.status_code == 401
    assert response.json() == {
        "errors": [
            {
                "attr": None,
                "code": "not_authenticated",
                "detail": "Authentication credentials were not provided.",
            },
        ],
        "type": "client_error",
    }


def test_api_users_list_authenticated():
    """
    Authenticated users should not be able to list users without a query.
    """
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    factories.UserFactory.create_batch(2)
    response = client.get(
        "/api/v1.0/users/",
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_api_users_list_query_inactive():
    """Inactive users should not be listed."""
    user = factories.UserFactory()
    org = user.organization
    client = APIClient()
    client.force_login(user)

    factories.UserFactory(
        email="john.doe@example.com", is_active=False, organization=org
    )
    lennon = factories.UserFactory(email="john.lennon@example.com", organization=org)

    # Use email query to get exact match
    response = client.get("/api/v1.0/users/?q=john.lennon@example.com")

    assert response.status_code == 200
    user_ids = [user["id"] for user in response.json()["results"]]
    assert user_ids == [str(lennon.id)]

    # Inactive user should not be returned even with exact match
    response = client.get("/api/v1.0/users/?q=john.doe@example.com")
    assert response.status_code == 200
    user_ids = [user["id"] for user in response.json()["results"]]
    assert user_ids == []


def test_api_users_list_query_short_queries():
    """Queries shorter than 3 characters should return an empty result set."""
    user = factories.UserFactory()
    org = user.organization
    client = APIClient()
    client.force_login(user)

    factories.UserFactory(email="john.doe@example.com", organization=org)

    response = client.get("/api/v1.0/users/?q=jo")
    assert response.status_code == 200
    assert response.json()["results"] == []

    response = client.get("/api/v1.0/users/?q=j")
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_api_users_list_limit(settings):  # pylint: disable=unused-argument
    """Results should be bounded even with many matching users."""
    user = factories.UserFactory()
    org = user.organization

    client = APIClient()
    client.force_login(user)

    for i in range(55):
        factories.UserFactory(email=f"alice.{i}@example.com", organization=org)

    # Partial match returns results (capped at 50)
    response = client.get("/api/v1.0/users/?q=alice")
    assert response.status_code == 200
    assert len(response.json()["results"]) == 50


def test_api_users_list_throttling_authenticated(settings):
    """
    Authenticated users should be throttled.
    """
    user = factories.UserFactory()
    client = APIClient()
    client.force_login(user)

    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["user_list_burst"] = "3/minute"

    for _i in range(3):
        response = client.get(
            "/api/v1.0/users/?q=alice",
        )
        assert response.status_code == 200

    response = client.get(
        "/api/v1.0/users/?q=alice",
    )
    assert response.status_code == 429


def test_api_users_list_query_email(settings):
    """
    Authenticated users should be able to search users by partial email.
    """

    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["user_list_burst"] = "9999/minute"

    user = factories.UserFactory()
    org = user.organization

    client = APIClient()
    client.force_login(user)

    dave = factories.UserFactory(email="david.bowman@work.com", organization=org)
    nicole = factories.UserFactory(email="nicole.bowman@work.com", organization=org)

    # Exact match works
    response = client.get("/api/v1.0/users/?q=david.bowman@work.com")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert str(dave.id) in user_ids

    # Partial email match works
    response = client.get("/api/v1.0/users/?q=bowman@work")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert str(dave.id) in user_ids
    assert str(nicole.id) in user_ids

    # Case-insensitive match works
    response = client.get("/api/v1.0/users/?q=David.Bowman@Work.COM")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert str(dave.id) in user_ids

    # Typos don't match
    response = client.get("/api/v1.0/users/?q=davig.bovman@worm.com")
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_api_users_list_query_email_partial_matching():
    """Partial email queries return matching users."""
    user = factories.UserFactory()
    org = user.organization

    client = APIClient()
    client.force_login(user)

    user1 = factories.UserFactory(
        email="alice.johnson@example.gouv.fr", organization=org
    )
    user2 = factories.UserFactory(
        email="alice.johnnson@example.gouv.fr", organization=org
    )
    factories.UserFactory(email="alice.kohlson@example.gouv.fr", organization=org)
    user4 = factories.UserFactory(
        email="alicia.johnnson@example.gouv.fr", organization=org
    )
    # Different org user should not appear
    other_org_user = factories.UserFactory(email="alice.johnnson@example.gov.uk")
    factories.UserFactory(email="alice.thomson@example.gouv.fr", organization=org)

    # Partial match on "alice.john" returns alice.johnson and alice.johnnson
    response = client.get("/api/v1.0/users/?q=alice.john")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert str(user1.id) in user_ids
    assert str(user2.id) in user_ids
    assert str(other_org_user.id) not in user_ids

    # Partial match on "alicia" returns alicia.johnnson (same org only)
    response = client.get("/api/v1.0/users/?q=alicia")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert user_ids == [str(user4.id)]


def test_api_users_list_query_by_name():
    """Users should be searchable by full name (partial, case-insensitive)."""
    user = factories.UserFactory()
    org = user.organization

    client = APIClient()
    client.force_login(user)

    alice = factories.UserFactory(
        email="alice@example.com", full_name="Alice Johnson", organization=org
    )
    bob = factories.UserFactory(
        email="bob@example.com", full_name="Bob Smith", organization=org
    )
    factories.UserFactory(
        email="charlie@example.com", full_name="Charlie Johnson", organization=org
    )

    # Search by first name
    response = client.get("/api/v1.0/users/?q=Alice")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert str(alice.id) in user_ids
    assert str(bob.id) not in user_ids

    # Search by last name matches multiple users
    response = client.get("/api/v1.0/users/?q=Johnson")
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2

    # Case-insensitive
    response = client.get("/api/v1.0/users/?q=bob")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert str(bob.id) in user_ids


def test_api_users_list_cross_org_isolation():
    """Users from different organizations should not see each other."""
    org1 = factories.OrganizationFactory(name="Org One")
    org2 = factories.OrganizationFactory(name="Org Two")

    user1 = factories.UserFactory(
        email="user1@org1.com", full_name="Shared Name", organization=org1
    )
    factories.UserFactory(
        email="user2@org2.com", full_name="Shared Name", organization=org2
    )

    client = APIClient()
    client.force_login(user1)

    # Search by shared name - should only return same-org user
    response = client.get("/api/v1.0/users/?q=Shared")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert str(user1.id) in user_ids
    assert len(user_ids) == 1

    # Search by cross-org email - should return nothing
    response = client.get("/api/v1.0/users/?q=user2@org2.com")
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_api_users_list_includes_self():
    """Search should include the requesting user if they match."""
    user = factories.UserFactory(email="alice@example.com", full_name="Alice Test")

    client = APIClient()
    client.force_login(user)

    # User should find themselves
    response = client.get("/api/v1.0/users/?q=alice")
    assert response.status_code == 200
    user_ids = [u["id"] for u in response.json()["results"]]
    assert str(user.id) in user_ids


def test_api_users_retrieve_me_anonymous():
    """Anonymous users should not be allowed to list users."""
    factories.UserFactory.create_batch(2)
    client = APIClient()
    response = client.get("/api/v1.0/users/me/")
    assert response.status_code == 401
    assert response.json() == {
        "errors": [
            {
                "attr": None,
                "code": "not_authenticated",
                "detail": "Authentication credentials were not provided.",
            },
        ],
        "type": "client_error",
    }


def test_api_users_retrieve_me_authenticated():
    """Authenticated users should be able to retrieve their own user via the "/users/me" path."""
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    factories.UserFactory.create_batch(2)
    response = client.get(
        "/api/v1.0/users/me/",
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "language": user.language,
        "timezone": str(user.timezone),
        "can_access": True,
        "can_admin": True,
        "organization": {
            "id": str(user.organization.id),
            "name": user.organization.name,
            "sharing_level": "freebusy",
        },
    }


def test_api_users_retrieve_anonymous():
    """Anonymous users should not be allowed to retrieve a user."""
    client = APIClient()
    user = factories.UserFactory()
    response = client.get(f"/api/v1.0/users/{user.id!s}/")

    assert response.status_code == 401
    assert response.json() == {
        "errors": [
            {
                "attr": None,
                "code": "not_authenticated",
                "detail": "Authentication credentials were not provided.",
            },
        ],
        "type": "client_error",
    }


def test_api_users_retrieve_authenticated_self():
    """
    Authenticated users should be allowed to retrieve their own user.
    The returned object should not contain the password.
    """
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    response = client.get(
        f"/api/v1.0/users/{user.id!s}/",
    )
    assert response.status_code == 405
    assert response.json() == {
        "errors": [
            {
                "attr": None,
                "code": "method_not_allowed",
                "detail": 'Method "GET" not allowed.',
            },
        ],
        "type": "client_error",
    }


def test_api_users_retrieve_authenticated_other():
    """
    Authenticated users should be able to retrieve another user's detail view with
    limited information.
    """
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    other_user = factories.UserFactory()

    response = client.get(
        f"/api/v1.0/users/{other_user.id!s}/",
    )
    assert response.status_code == 405
    assert response.json() == {
        "errors": [
            {
                "attr": None,
                "code": "method_not_allowed",
                "detail": 'Method "GET" not allowed.',
            },
        ],
        "type": "client_error",
    }


def test_api_users_create_anonymous():
    """Anonymous users should not be able to create users via the API."""
    response = APIClient().post(
        "/api/v1.0/users/",
        {
            "language": "fr-fr",
            "password": "mypassword",
        },
    )
    assert response.status_code == 401
    assert response.json() == {
        "errors": [
            {
                "attr": None,
                "code": "not_authenticated",
                "detail": "Authentication credentials were not provided.",
            },
        ],
        "type": "client_error",
    }

    assert models.User.objects.exists() is False


def test_api_users_create_authenticated():
    """Authenticated users should not be able to create users via the API."""
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    response = client.post(
        "/api/v1.0/users/",
        {
            "language": "fr-fr",
            "password": "mypassword",
        },
        format="json",
    )
    assert response.status_code == 405
    assert response.json() == {
        "errors": [
            {
                "attr": None,
                "code": "method_not_allowed",
                "detail": 'Method "POST" not allowed.',
            },
        ],
        "type": "client_error",
    }

    assert models.User.objects.exclude(id=user.id).exists() is False


def test_api_users_update_anonymous():
    """Anonymous users should not be able to update users via the API."""
    user = factories.UserFactory()

    old_user_values = dict(serializers.UserSerializer(instance=user).data)
    new_user_values = serializers.UserSerializer(instance=factories.UserFactory()).data

    response = APIClient().put(
        f"/api/v1.0/users/{user.id!s}/",
        new_user_values,
        format="json",
    )

    assert response.status_code == 401
    assert response.json() == {
        "errors": [
            {
                "attr": None,
                "code": "not_authenticated",
                "detail": "Authentication credentials were not provided.",
            },
        ],
        "type": "client_error",
    }

    user.refresh_from_db()
    user_values = dict(serializers.UserSerializer(instance=user).data)
    for key, value in user_values.items():
        assert value == old_user_values[key]


def test_api_users_update_authenticated_self():
    """
    Authenticated users should be able to update their own user but only "language",
    "timezone" fields.
    """
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    old_user_values = dict(serializers.UserSerializer(instance=user).data)
    new_user_values = dict(
        serializers.UserSerializer(instance=factories.UserFactory()).data
    )

    response = client.put(
        f"/api/v1.0/users/{user.id!s}/",
        new_user_values,
        format="json",
    )

    assert response.status_code == 200
    user.refresh_from_db()
    user_values = dict(serializers.UserSerializer(instance=user).data)
    for key, value in user_values.items():
        if key in ["language", "timezone"]:
            assert value == new_user_values[key]
        else:
            assert value == old_user_values[key]


def test_api_users_update_authenticated_other():
    """Authenticated users should not be allowed to update other users."""
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    user = factories.UserFactory()
    old_user_values = dict(serializers.UserSerializer(instance=user).data)
    new_user_values = serializers.UserSerializer(instance=factories.UserFactory()).data

    response = client.put(
        f"/api/v1.0/users/{user.id!s}/",
        new_user_values,
        format="json",
    )

    assert response.status_code == 403
    user.refresh_from_db()
    user_values = dict(serializers.UserSerializer(instance=user).data)
    for key, value in user_values.items():
        assert value == old_user_values[key]


def test_api_users_patch_anonymous():
    """Anonymous users should not be able to patch users via the API."""
    user = factories.UserFactory()

    old_user_values = dict(serializers.UserSerializer(instance=user).data)
    new_user_values = dict(
        serializers.UserSerializer(instance=factories.UserFactory()).data
    )

    for key, new_value in new_user_values.items():
        response = APIClient().patch(
            f"/api/v1.0/users/{user.id!s}/",
            {key: new_value},
            format="json",
        )
        assert response.status_code == 401
        assert response.json() == {
            "errors": [
                {
                    "attr": None,
                    "code": "not_authenticated",
                    "detail": "Authentication credentials were not provided.",
                },
            ],
            "type": "client_error",
        }

    user.refresh_from_db()
    user_values = dict(serializers.UserSerializer(instance=user).data)
    for key, value in user_values.items():
        assert value == old_user_values[key]


def test_api_users_patch_authenticated_self():
    """
    Authenticated users should be able to patch their own user but only "language",
    "timezone" fields.
    """
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    old_user_values = dict(serializers.UserSerializer(instance=user).data)
    new_user_values = dict(
        serializers.UserSerializer(instance=factories.UserFactory()).data
    )

    for key, new_value in new_user_values.items():
        response = client.patch(
            f"/api/v1.0/users/{user.id!s}/",
            {key: new_value},
            format="json",
        )
        assert response.status_code == 200

    user.refresh_from_db()
    user_values = dict(serializers.UserSerializer(instance=user).data)
    for key, value in user_values.items():
        if key in ["language", "timezone"]:
            assert value == new_user_values[key]
        else:
            assert value == old_user_values[key]


def test_api_users_patch_authenticated_other():
    """Authenticated users should not be allowed to patch other users."""
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    user = factories.UserFactory()
    old_user_values = dict(serializers.UserSerializer(instance=user).data)
    new_user_values = dict(
        serializers.UserSerializer(instance=factories.UserFactory()).data
    )

    for key, new_value in new_user_values.items():
        response = client.put(
            f"/api/v1.0/users/{user.id!s}/",
            {key: new_value},
            format="json",
        )
        assert response.status_code == 403

    user.refresh_from_db()
    user_values = dict(serializers.UserSerializer(instance=user).data)
    for key, value in user_values.items():
        assert value == old_user_values[key]


def test_api_users_delete_list_anonymous():
    """Anonymous users should not be allowed to delete a list of users."""
    factories.UserFactory.create_batch(2)

    client = APIClient()
    response = client.delete("/api/v1.0/users/")

    assert response.status_code == 401
    assert models.User.objects.count() == 2


def test_api_users_delete_list_authenticated():
    """Authenticated users should not be allowed to delete a list of users."""
    factories.UserFactory.create_batch(2)
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    response = client.delete(
        "/api/v1.0/users/",
    )

    assert response.status_code == 405
    assert models.User.objects.count() == 3


def test_api_users_delete_anonymous():
    """Anonymous users should not be allowed to delete a user."""
    user = factories.UserFactory()

    response = APIClient().delete(f"/api/v1.0/users/{user.id!s}/")

    assert response.status_code == 401
    assert models.User.objects.count() == 1


def test_api_users_delete_authenticated():
    """
    Authenticated users should not be allowed to delete a user other than themselves.
    """
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    other_user = factories.UserFactory()

    response = client.delete(
        f"/api/v1.0/users/{other_user.id!s}/",
    )

    assert response.status_code == 405
    assert models.User.objects.count() == 2


def test_api_users_delete_self():
    """Authenticated users should not be able to delete their own user."""
    user = factories.UserFactory()

    client = APIClient()
    client.force_login(user)

    response = client.delete(
        f"/api/v1.0/users/{user.id!s}/",
    )

    assert response.status_code == 405
    assert models.User.objects.count() == 1
