"""API endpoints for calendar setup and Messages mailbox integration."""

import logging

from django.conf import settings

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.services.setup_service import SetupService, SetupServiceError
from core.tasks import sync_mailbox_task

logger = logging.getLogger(__name__)


class MailboxListView(APIView):
    """GET /api/v1.0/setup/mailboxes/

    Returns the current user's Messages mailboxes and syncs CalDAV shares.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List mailboxes and sync their ACLs."""
        if not settings.FEATURE_MESSAGES_INTEGRATION:
            return Response(
                {
                    "available_mailboxes": [],
                    "active_mailbox_calendars": [],
                }
            )

        try:
            result = SetupService().sync_user_mailboxes(request.user)
            return Response(result)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to fetch mailboxes for %s", request.user.pk)
            return Response(
                {"error": "Failed to fetch mailboxes"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SetupView(APIView):
    """POST /api/v1.0/setup/

    Bootstrap a user's calendar. Single endpoint for both standalone and mailbox.

    Body:
        {"name": "My Calendar"}                              → standalone
        {"name": "Contact Team", "mailbox_email": "contact@company.com"}  → mailbox
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Create a standalone or mailbox-backed calendar."""
        name = request.data.get("name", "").strip()
        mailbox_email = request.data.get("mailbox_email")
        color = request.data.get("color")

        if mailbox_email and not name:
            name = mailbox_email
        if not name:
            return Response(
                {"code": "name_required", "error": "name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = SetupService().setup(
                request.user, name, mailbox_email=mailbox_email, color=color
            )
        except SetupServiceError as exc:
            logger.warning(
                "Setup rejected for user %s (mailbox=%s, code=%s): %s",
                request.user.pk,
                mailbox_email,
                exc.code,
                exc,
            )
            # The message can hold internal details, so return only the code.
            return Response(
                {"code": exc.code, "error": "Calendar setup failed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to setup calendar for %s", request.user.pk)
            return Response(
                {"error": "Failed to create calendar"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # The other mailbox users get the calendar from the worker, because
        # one sync per user can take longer than the request timeout. The
        # sync keeps the color of the caller: it only updates the access.
        # The calendar exists, so a failed enqueue does not fail the setup.
        # The scheduled sync shares the calendar later.
        if mailbox_email:
            try:
                sync_mailbox_task.delay(mailbox_email)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Failed to enqueue the sync of %s", mailbox_email)
        return Response(result, status=status.HTTP_201_CREATED)
