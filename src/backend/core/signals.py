"""
Declare and configure the signals for the calendars core application
"""

import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from core.entitlements import EntitlementsUnavailableError, get_user_entitlements
from core.services.caldav_service import CalDAVHTTPClient, CalendarService

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def provision_default_calendar(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """
    Auto-provision a default calendar when a new user is created.
    """
    if not created:
        return

    # Skip calendar creation if CalDAV server is not configured
    if not settings.CALDAV_URL:
        return

    # Check entitlements before creating calendar — fail-closed:
    # never create a calendar if we can't confirm access.
    try:
        entitlements = get_user_entitlements(instance.sub, instance.email)
        if not entitlements.get("can_access", False):
            logger.info(
                "Skipped calendar creation for %s (not entitled)",
                instance.email,
            )
            return
    except EntitlementsUnavailableError:
        logger.warning(
            "Entitlements unavailable for %s, skipping calendar creation",
            instance.email,
        )
        return

    try:
        service = CalendarService()
        service.create_default_calendar(instance)
        logger.info("Created default calendar for user %s", instance.pk)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception(
            "Failed to create default calendar for user %s",
            instance.pk,
        )


@receiver(pre_delete, sender=User)
def delete_user_caldav_data(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Schedule CalDAV data cleanup when a user is deleted.

    Uses on_commit so the external CalDAV call only fires after
    the DB transaction commits — avoids orphaned state on rollback.
    """
    email = instance.email
    if not email:
        return

    if not settings.CALDAV_INTERNAL_API_KEY:
        return

    api_key = settings.CALDAV_INTERNAL_API_KEY

    def _cleanup():
        try:
            http = CalDAVHTTPClient()
            http.request(
                "POST",
                instance,
                "internal-api/users/delete",
                data=json.dumps({"email": email}).encode("utf-8"),
                content_type="application/json",
                extra_headers={"X-Internal-Api-Key": api_key},
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Failed to clean up CalDAV data for user %s",
                email,
            )

    transaction.on_commit(_cleanup)
