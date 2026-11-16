"""Tests for the task admin."""

import pytest
from django_dramatiq.models import Task

from core import factories
from core.task_utils import AdminMiddleware
from core.tasks import InvitationSendError, send_invitation_task

pytestmark = pytest.mark.django_db


@pytest.fixture(name="superuser_client")
def fixture_superuser_client(client, settings):
    """Return a client logged in as a superuser."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    client.force_login(factories.UserFactory(is_staff=True, is_superuser=True))
    return client


EMPTY_ICS = "BEGIN:VCALENDAR\r\nEND:VCALENDAR"


def _message(icalendar_data=EMPTY_ICS):
    return send_invitation_task.message(
        sender_email="alice@example.com",
        recipient_email="bob@example.com",
        method="REQUEST",
        icalendar_data=icalendar_data,
    )


def _create_task(icalendar_data, status=Task.STATUS_DONE, traceback=None):
    message = _message(icalendar_data)
    if traceback:
        message.options["traceback"] = traceback
    Task.tasks.create_or_update_from_message(
        message,
        status=status,
        actor_name=message.actor_name,
        queue_name=message.queue_name,
    )
    return message


def test_task_list_shows_a_short_summary(superuser_client):
    """The task list does not show the full ICS data of a task."""
    _create_task(
        "BEGIN:VCALENDAR\r\n" + "X-FILLER:abcdefghij\r\n" * 50 + "END:VCALENDAR"
    )

    response = superuser_client.get("/admin/django_dramatiq/task/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "send_invitation_task(" in content
    assert "X-FILLER" not in content


def test_task_details_are_escaped(superuser_client):
    """HTML in the ICS data or in the traceback is not rendered."""
    payload = "<img src=x onerror=alert(1)>"
    message = _create_task(
        f"BEGIN:VCALENDAR\r\nDESCRIPTION:{payload}\r\nEND:VCALENDAR",
        status=Task.STATUS_FAILED,
        traceback=f"InvitationSendError: {payload}",
    )

    response = superuser_client.get(
        f"/admin/django_dramatiq/task/{message.message_id}/change/"
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert payload not in content
    assert "&lt;img src=x onerror=alert(1)&gt;" in content


def test_admin_middleware_deletes_a_done_email_task():
    """The task table does not keep a done email task."""
    message = _create_task(EMPTY_ICS, Task.STATUS_RUNNING)

    AdminMiddleware().after_process_message(None, message)

    assert not Task.tasks.filter(id=message.message_id).exists()


def test_admin_middleware_keeps_a_failed_email_task():
    """The task table keeps a failed email task, for inspection."""
    message = _create_task(EMPTY_ICS, Task.STATUS_RUNNING)

    AdminMiddleware().after_process_message(
        None, message, exception=InvitationSendError("failed")
    )

    assert Task.tasks.get(id=message.message_id).status == Task.STATUS_FAILED


def test_admin_middleware_does_not_recreate_a_done_email_task():
    """A late enqueue hook does not bring back the record of a done task."""
    message = _create_task(EMPTY_ICS, Task.STATUS_RUNNING)
    middleware = AdminMiddleware()
    middleware.after_process_message(None, message)

    middleware.after_enqueue(None, message, None)

    assert not Task.tasks.filter(id=message.message_id).exists()


def test_admin_middleware_records_a_delayed_retry():
    """A retry is queued with a delay, so its record shows it."""
    message = _message()

    AdminMiddleware().after_enqueue(None, message, 60_000)

    assert Task.tasks.get(id=message.message_id).status == Task.STATUS_DELAYED
