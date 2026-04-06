"""
Declare and configure the signals for the calendars core application
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from core.services.caldav_service import CalDAVHTTPClient

logger = logging.getLogger(__name__)
User = get_user_model()


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

    def _cleanup():
        try:
            http = CalDAVHTTPClient()
            http.internal_request(
                "POST",
                instance,
                "internal-api/users/delete",
                json={"email": email},
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Failed to clean up CalDAV data for user %s",
                email,
            )

    transaction.on_commit(_cleanup)
