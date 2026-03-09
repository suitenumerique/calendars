"""Fixtures for tests in the calendars core application"""

import base64

from django.conf import settings
from django.core.cache import cache

import pytest
import responses

from core import factories
from core.tests.utils.urls import reload_urls

USER = "user"


def _has_caldav_marker(request):
    """Check if the test has the xdist_group('caldav') marker."""
    marker = request.node.get_closest_marker("xdist_group")
    return marker is not None and marker.args and marker.args[0] == "caldav"


@pytest.fixture(autouse=True)
def truncate_caldav_tables(request, django_db_setup, django_db_blocker):  # pylint: disable=unused-argument
    """Truncate CalDAV tables before each CalDAV E2E test.

    Only runs for tests marked with @pytest.mark.xdist_group("caldav").
    Non-CalDAV tests don't touch the SabreDAV database, so truncating
    from their worker would corrupt state for CalDAV tests running
    concurrently on another xdist worker.
    """
    if not _has_caldav_marker(request):
        yield
        return

    import psycopg  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    db_settings = settings.DATABASES["default"]
    conn = psycopg.connect(
        host=db_settings["HOST"],
        port=db_settings["PORT"],
        dbname="calendars",  # SabreDAV always uses this DB
        user=db_settings["USER"],
        password=db_settings["PASSWORD"],
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:  # pylint: disable=no-member
            for table in [
                "calendarobjects",
                "calendarinstances",
                "calendars",
                "principals",
            ]:
                cur.execute(f"TRUNCATE TABLE {table} CASCADE")
    finally:
        conn.close()  # pylint: disable=no-member
    yield


@pytest.fixture(autouse=True)
def disconnect_caldav_signals_for_unit_tests(request):
    """Disconnect CalDAV signal handlers for non-CalDAV tests.

    Prevents non-CalDAV tests from hitting the real SabreDAV server
    (e.g. via post_save signal when UserFactory creates a user),
    which would interfere with CalDAV E2E tests running concurrently
    on another xdist worker.
    """
    if _has_caldav_marker(request):
        yield
        return

    from django.contrib.auth import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        get_user_model,
    )
    from django.db.models.signals import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        post_save,
        pre_delete,
    )

    from core.signals import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        delete_user_caldav_data,
        provision_default_calendar,
    )

    user_model = get_user_model()
    post_save.disconnect(provision_default_calendar, sender=user_model)
    pre_delete.disconnect(delete_user_caldav_data, sender=user_model)
    yield
    post_save.connect(provision_default_calendar, sender=user_model)
    pre_delete.connect(delete_user_caldav_data, sender=user_model)


@pytest.fixture(autouse=True)
def clear_cache():
    """Fixture to clear the cache after each test."""
    yield
    cache.clear()
    # Clear functools.cache for functions decorated with @functools.cache


def resource_server_backend_setup(settings):  # pylint: disable=redefined-outer-name
    """
    A fixture to create a user token for testing.
    """
    assert (
        settings.OIDC_RS_BACKEND_CLASS
        == "lasuite.oidc_resource_server.backend.ResourceServerBackend"
    )

    settings.OIDC_RESOURCE_SERVER_ENABLED = True
    settings.OIDC_RS_CLIENT_ID = "some_client_id"
    settings.OIDC_RS_CLIENT_SECRET = "some_client_secret"

    settings.OIDC_OP_URL = "https://oidc.example.com"
    settings.OIDC_VERIFY_SSL = False
    settings.OIDC_TIMEOUT = 5
    settings.OIDC_PROXY = None
    settings.OIDC_OP_JWKS_ENDPOINT = "https://oidc.example.com/jwks"
    settings.OIDC_OP_INTROSPECTION_ENDPOINT = "https://oidc.example.com/introspect"
    settings.OIDC_RS_SCOPES = ["openid", "groups"]
    settings.OIDC_RS_ALLOWED_AUDIENCES = ["some_service_provider"]


@pytest.fixture
def resource_server_backend_conf(settings):  # pylint: disable=redefined-outer-name
    """
    A fixture to create a user token for testing.
    """
    resource_server_backend_setup(settings)
    reload_urls()


@pytest.fixture
def resource_server_backend(settings):  # pylint: disable=redefined-outer-name
    """
    A fixture to create a user token for testing.
    Including a mocked introspection endpoint.
    """
    resource_server_backend_setup(settings)
    reload_urls()

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://oidc.example.com/introspect",
            json={
                "iss": "https://oidc.example.com",
                "aud": "some_client_id",  # settings.OIDC_RS_CLIENT_ID
                "sub": "very-specific-sub",
                "client_id": "some_service_provider",
                "scope": "openid groups",
                "active": True,
            },
        )

        yield rsps


@pytest.fixture
def user_specific_sub():
    """
    A fixture to create a user token for testing.
    """
    user = factories.UserFactory(sub="very-specific-sub")

    yield user


def build_authorization_bearer(token):
    """
    Build an Authorization Bearer header value from a token.

    This can be used like this:
    client.post(
        ...
        HTTP_AUTHORIZATION=f"Bearer {build_authorization_bearer('some_token')}",
    )
    """
    return base64.b64encode(token.encode("utf-8")).decode("utf-8")


@pytest.fixture
def user_token():
    """
    A fixture to create a user token for testing.
    """
    return build_authorization_bearer("some_token")
