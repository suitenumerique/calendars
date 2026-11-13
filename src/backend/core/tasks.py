"""Background tasks for the calendars core application."""

# pylint: disable=import-outside-toplevel

import logging
from dataclasses import asdict

from django.conf import settings

from core.services.calendar_invitation_service import calendar_invitation_service
from core.services.import_service import ICSImportService
from core.task_utils import register_task, set_task_progress

logger = logging.getLogger(__name__)


class InvitationSendError(Exception):
    """A calendar email was not sent."""


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


# No retry: a retry after a partial failure can send the same email twice.
@register_task(queue="default", max_retries=0, store_results=False)
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
    success = calendar_invitation_service.send_invitation(
        sender_email=sender_email,
        recipient_email=recipient_email,
        method=method,
        icalendar_data=icalendar_data,
        is_mailbox=is_mailbox,
        org_id=org_id,
        is_new_attendee=is_new_attendee,
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


@register_task(queue="sync")
def sync_all_mailbox_acls():
    """Sync Messages mailbox ACLs for all users.

    Scheduled externally (cron). Iterates all users with an org and
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
    for user in User.objects.filter(organization__isnull=False).iterator():
        try:
            service.sync_user_mailboxes(user)
            total += 1
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("sync_all_mailbox_acls: failed for user %s", user.pk)
            errors += 1

    logger.info("sync_all_mailbox_acls: synced %d users, %d errors", total, errors)
