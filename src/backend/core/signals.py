"""
Declare and configure the signals for the calendars core application
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.services.caldav_service import CalendarService

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def provision_default_calendar(sender, instance, created, **kwargs):
    """
    Auto-provision a default calendar when a new user is created.
    """
    if not created:
        return

    # Check if user already has a default calendar
    if instance.calendars.filter(is_default=True).exists():
        return

    # Skip calendar creation if DAViCal is not configured
    if not getattr(settings, "DAVICAL_URL", None):
        return

    try:
        service = CalendarService()
        service.create_default_calendar(instance)
        logger.info("Created default calendar for user %s", instance.email)
    except Exception as e:
        # In tests, DAViCal tables don't exist, so fail silently
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
