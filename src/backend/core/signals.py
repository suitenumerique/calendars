"""
Declare and configure the signals for the calendars core application
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
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
        if not entitlements.get("can_access", True):
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
        logger.info("Created default calendar for user %s", instance.email)
    except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        # In tests, CalDAV server may not be available, so fail silently
        # Check if it's a database error that suggests we're in tests
        error_str = str(e).lower()
        if "does not exist" in error_str or "relation" in error_str:
            # Likely in test environment, fail silently
            logger.debug(
                "Skipped calendar creation for user %s (likely test environment): %s",
                instance.email,
                str(e),
            )
        else:
            # Real error, log it
            logger.error(
                "Failed to create default calendar for user %s: %s",
                instance.email,
                str(e),
            )


@receiver(pre_delete, sender=User)
def delete_user_caldav_data(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """Clean up CalDAV data when a user is deleted."""
    if not instance.email:
        return

    if not settings.CALDAV_INTERNAL_API_KEY:
        return

    try:
        http = CalDAVHTTPClient()
        http.request(
            "DELETE",
            instance.email,
            f"internal-api/users/{instance.email}",
            extra_headers={"X-Internal-Api-Key": settings.CALDAV_INTERNAL_API_KEY},
        )
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception(
            "Failed to clean up CalDAV data for user %s",
            instance.email,
        )
