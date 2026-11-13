"""Tests for the task admin."""

import pytest
from django_dramatiq.models import Task

from core import factories
from core.tasks import send_invitation_task

pytestmark = pytest.mark.django_db


@pytest.fixture(name="admin_client")
def fixture_admin_client(client, settings):
    """Return a client logged in as a superuser."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    client.force_login(factories.UserFactory(is_staff=True, is_superuser=True))
    return client


def _create_task(icalendar_data, status=Task.STATUS_DONE, traceback=None):
    message = send_invitation_task.message(
        sender_email="alice@example.com",
        recipient_email="bob@example.com",
        method="REQUEST",
        icalendar_data=icalendar_data,
    )
    if traceback:
        message.options["traceback"] = traceback
    return Task.tasks.create_or_update_from_message(
        message,
        status=status,
        actor_name=message.actor_name,
        queue_name=message.queue_name,
    )


def test_task_list_shows_a_short_summary(admin_client):
    """The task list does not show the full ICS data of a task."""
    _create_task(
        "BEGIN:VCALENDAR\r\n" + "X-FILLER:abcdefghij\r\n" * 50 + "END:VCALENDAR"
    )

    response = admin_client.get("/admin/django_dramatiq/task/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "send_invitation_task(" in content
    assert "X-FILLER" not in content


def test_task_details_are_escaped(admin_client):
    """HTML in the ICS data or in the traceback is not rendered."""
    payload = "<img src=x onerror=alert(1)>"
    task = _create_task(
        f"BEGIN:VCALENDAR\r\nDESCRIPTION:{payload}\r\nEND:VCALENDAR",
        status=Task.STATUS_FAILED,
        traceback=f"InvitationSendError: {payload}",
    )

    response = admin_client.get(f"/admin/django_dramatiq/task/{task.pk}/change/")

    assert response.status_code == 200
    content = response.content.decode()
    assert payload not in content
    assert "&lt;img src=x onerror=alert(1)&gt;" in content
