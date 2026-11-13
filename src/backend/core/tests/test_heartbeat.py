"""Tests for the heartbeat endpoint."""

from unittest import mock

from django.db.utils import OperationalError

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_heartbeat_ok():
    """An anonymous client gets a 200 when the database is reachable."""
    response = APIClient().get("/__heartbeat__/")

    assert response.status_code == 200
    assert response.content == b"OK"


def test_heartbeat_database_unavailable():
    """The endpoint returns a 500 when the database is not reachable."""
    with mock.patch(
        "calendars.urls.connection.ensure_connection",
        side_effect=OperationalError("connection refused"),
    ):
        response = APIClient().get("/__heartbeat__/")

    assert response.status_code == 500
    assert response.content == b"DB Unavailable"
