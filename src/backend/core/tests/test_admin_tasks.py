"""Tests for the task admin."""

import pytest
from django_dramatiq.models import Task

from core import factories
from core.tasks import send_invitation_task

pytestmark = pytest.mark.django_db


def test_task_list_shows_a_short_summary(client, settings):
    """The task list does not show the full ICS data of a task."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    ics = "BEGIN:VCALENDAR\r\n" + "X-FILLER:abcdefghij\r\n" * 50 + "END:VCALENDAR"
    message = send_invitation_task.message(
        sender_email="alice@example.com",
        recipient_email="bob@example.com",
        method="REQUEST",
        icalendar_data=ics,
    )
    Task.tasks.create_or_update_from_message(
        message,
        status=Task.STATUS_DONE,
        actor_name=message.actor_name,
        queue_name=message.queue_name,
    )
    client.force_login(factories.UserFactory(is_staff=True, is_superuser=True))

    response = client.get("/admin/django_dramatiq/task/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "send_invitation_task(" in content
    assert "X-FILLER" not in content
