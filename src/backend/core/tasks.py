"""Background tasks for the calendars core application."""

# pylint: disable=import-outside-toplevel

import logging
from dataclasses import asdict
from datetime import UTC, datetime

from django.conf import settings

from dramatiq.middleware import CurrentMessage

from core.services.calendar_invitation_service import (
    InvitationNotSentError,
    calendar_invitation_service,
)
from core.services.import_service import ICSImportService
from core.task_utils import register_task, set_task_progress

logger = logging.getLogger(__name__)


class InvitationSendError(Exception):
    """The server did not accept the calendar email, or the result is unknown."""


@register_task(queue="import")
def import_events_task(user_id, caldav_path, ics_data_hex):
    """Import events from ICS data in the background.

    Parameters are kept JSON-serialisable:
    - user_id: pk of the User who triggered the import
    - caldav_path: target CalDAV calendar path
    - ics_data_hex: ICS bytes encoded as hex string
    """
    from core.models import User  # noqa: PLC0415

    set_task_progress(0, {"message": "Starting import..."})

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("import_events_task: user %s not found", user_id)
        return {
            "status": "FAILURE",
            "result": None,
            "error": "User not found",
        }

    ics_data = bytes.fromhex(ics_data_hex)
    set_task_progress(10, {"message": "Sending to CalDAV server..."})

    service = ICSImportService()
    result = service.import_events(user, caldav_path, ics_data)

    set_task_progress(100, {"message": "Import complete"})

    result_dict = asdict(result)
    return {
        "status": "SUCCESS",
        "result": result_dict,
        "error": None,
    }


INVITATION_SEND_RETRIES = 6


def _retry_when_not_sent(retries, exception):
    """Retry only when the server did not accept the email.

    Then a retry cannot send the same email twice.
    """
    return (
        isinstance(exception, InvitationNotSentError)
        and retries < INVITATION_SEND_RETRIES
    )


# The task retries 6 times. The wait doubles at each retry, with a random
# part. The first wait is 30 to 60 seconds.
@register_task(
    queue="default",
    retry_when=_retry_when_not_sent,
    min_backoff=60_000,
    store_results=False,
)
def send_invitation_task(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
    sender_email,
    recipient_email,
    method,
    icalendar_data,
    is_mailbox=False,
    org_id="",
    is_new_attendee=False,
):
    """Send one calendar email for an iTIP message from the CalDAV server."""
    via = "messages" if is_mailbox else "smtp"
    # The Date header is the time of the save, also after a retry.
    message = CurrentMessage.get_current_message()
    email_date = (
        datetime.fromtimestamp(message.message_timestamp / 1000, tz=UTC)
        if message
        else None
    )
    success = calendar_invitation_service.send_invitation(
        sender_email=sender_email,
        recipient_email=recipient_email,
        method=method,
        icalendar_data=icalendar_data,
        is_mailbox=is_mailbox,
        org_id=org_id,
        is_new_attendee=is_new_attendee,
        email_date=email_date,
    )
    if not success:
        # Raise so that the task shows as failed. The worker logs the error.
        raise InvitationSendError(
            f"Failed to send calendar {method}: {sender_email} -> {recipient_email} "
            f"(via {via})"
        )

    logger.info(
        "Sent calendar %s: %s -> %s (via %s)",
        method,
        sender_email,
        recipient_email,
        via,
    )


# The cron runs this task every 15 minutes, and the next run does the
# same work. Thus a failed run is not retried, and a message older than
# 15 minutes is dropped.
# The time limit stops a run after one hour. It is longer than the cron
# interval on purpose. A run that stops early does not sync all the users.
# With a short limit, this can occur at each run, and the same users can
# stay out of sync.
# Two runs can overlap. SetupService.sync_user_mailboxes locks the user,
# so two syncs of one user do not interleave.
@register_task(
    queue="sync",
    time_limit=60 * 60 * 1000,
    max_age=15 * 60 * 1000,
    max_retries=0,
    store_results=False,
)
def sync_all_mailbox_acls():
    """Sync Messages mailbox ACLs for all users.

    Scheduled externally (cron). Iterates all users with an email and
    syncs their mailbox shares via the Messages API.
    """
    if not settings.FEATURE_MESSAGES_INTEGRATION:
        logger.info("sync_all_mailbox_acls: Messages integration disabled, skipping")
        return

    from django.contrib.auth import get_user_model  # noqa: PLC0415

    from core.services.messages_service import MessagesServiceError  # noqa: PLC0415
    from core.services.setup_service import SetupService  # noqa: PLC0415

    User = get_user_model()  # pylint: disable=invalid-name

    # Eagerly probe ``service.messages`` so a missing Messages
    # configuration fails fast with a single error log instead of
    # silently exploding once per user inside the loop below. We can't
    # do this from ``SetupService.__init__`` itself: ``SetupService``
    # is also used for standalone (non-mailbox) calendar creation,
    # which legitimately runs without Messages settings configured.
    try:
        service = SetupService()
        _ = service.messages
    except MessagesServiceError as exc:
        logger.error("sync_all_mailbox_acls: cannot init service: %s", exc)
        return

    # Future: sync based on mailboxes instead of users for efficiency.
    total = 0
    errors = 0
    # A user without an email cannot have mailbox access.
    users = User.objects.exclude(email__isnull=True).exclude(email="")
    for user in users.iterator():
        try:
            service.sync_user_mailboxes(user)
            total += 1
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("sync_all_mailbox_acls: failed for user %s", user.pk)
            errors += 1

    logger.log(
        logging.WARNING if errors else logging.INFO,
        "sync_all_mailbox_acls: synced %d users, %d errors",
        total,
        errors,
    )


# A failed sync is not retried. The next scheduled sync of all users
# does the same work.
@register_task(queue="sync", max_retries=0, store_results=False)
def sync_mailbox_task(mailbox_email):
    """Sync the shares of each Calendars user of a mailbox."""
    from core.services.setup_service import SetupService  # noqa: PLC0415

    SetupService().sync_mailbox(mailbox_email)
