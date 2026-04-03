"""Background tasks for the calendars core application."""

# pylint: disable=import-outside-toplevel

import logging
from dataclasses import asdict

from django.conf import settings

from core.services.import_service import ICSImportService
from core.task_utils import register_task, set_task_progress

logger = logging.getLogger(__name__)


@register_task(queue="sync")
def sync_one_subscription(channel_id):
    """Sync a single external calendar subscription."""
    from core.services.subscription_sync_service import (  # noqa: PLC0415
        SubscriptionSyncService,
    )

    service = SubscriptionSyncService()
    return service.sync_channel(channel_id)


@register_task(queue="sync")
def sync_all_subscriptions():
    """Fan out sync tasks for all active subscriptions due for sync."""
    from django.utils import timezone as tz  # noqa: PLC0415

    from core.models import Channel  # noqa: PLC0415

    now = tz.now()
    channels = Channel.objects.filter(
        type="ical-subscription",
        is_active=True,
    ).iterator(chunk_size=500)

    dispatched = 0
    for channel in channels:
        sync_interval = max(channel.settings.get("sync_interval", 300), 1)
        last_sync_at = channel.settings.get("last_sync_at")

        # Check if channel is due for sync
        if last_sync_at:
            from django.utils.dateparse import (  # noqa: PLC0415
                parse_datetime,
            )

            last_sync = parse_datetime(last_sync_at)
            if last_sync and (now - last_sync).total_seconds() < sync_interval:
                continue

        # Stagger delay based on channel ID (deterministic across restarts)
        import uuid  # noqa: PLC0415

        delay_ms = (int(uuid.UUID(str(channel.pk))) % sync_interval) * 1000
        sync_one_subscription.send_with_options(
            args=(str(channel.pk),),
            delay=delay_ms,
        )
        dispatched += 1

    logger.info("Dispatched %d subscription sync tasks", dispatched)
    return dispatched


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
