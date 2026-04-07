"""Management command to resync Messages mailbox ACLs.

Can sync from either direction:
- Per user: syncs all mailbox shares for a user (or all users)
- Per mailbox: syncs shares for all users of a specific mailbox

Usage:
    python manage.py sync_mailbox_acls                        # all users
    python manage.py sync_mailbox_acls --email alice@co       # one user
    python manage.py sync_mailbox_acls --mailbox contact@co   # one mailbox
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.services.messages_service import MessagesServiceError
from core.services.setup_service import SetupService

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Sync Messages mailbox ACLs to CalDAV shares."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            help="Sync only this user (by OIDC email).",
        )
        parser.add_argument(
            "--mailbox",
            help="Sync all users of this mailbox (by mailbox email).",
        )

    def handle(self, *args, **options):
        if not settings.FEATURE_MESSAGES_INTEGRATION:
            self.stderr.write("FEATURE_MESSAGES_INTEGRATION is disabled.")
            return

        # Eagerly probe ``service.messages`` so a missing Messages
        # configuration fails fast here instead of silently exploding
        # once per user inside the loop below. ``SetupService.__init__``
        # itself stays lazy on purpose: standalone calendar creation
        # uses ``SetupService`` too and legitimately runs without
        # Messages settings configured.
        try:
            service = SetupService()
            _ = service.messages
        except MessagesServiceError as exc:
            self.stderr.write(f"Cannot initialize sync service: {exc}")
            return

        mailbox = options.get("mailbox")
        if mailbox:
            self._sync_mailbox(service, mailbox)
            return

        self._sync_users(service, options.get("email"))

    def _sync_mailbox(self, service, mailbox_email):
        """Sync shares for all users of a specific mailbox."""
        # Need a caller for internal API auth — use any admin or first user
        caller = User.objects.first()
        if not caller:
            self.stderr.write("No users in the database.")
            return

        try:
            count = service.sync_mailbox(caller, mailbox_email)
            self.stdout.write(f"Synced {count} user(s) for mailbox {mailbox_email}.")
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to sync mailbox %s", mailbox_email)
            self.stderr.write(f"Failed to sync mailbox {mailbox_email}.")

    def _sync_users(self, service, email=None):
        """Sync all mailbox shares for users."""
        if email:
            users = User.objects.filter(email=email)
            if not users.exists():
                self.stderr.write(f"User {email} not found.")
                return
        else:
            users = User.objects.all()

        total = users.count()
        synced = 0
        errors = 0

        for user in users.iterator():
            try:
                result = service.sync_user_mailboxes(user)
                n_calendars = len(result.get("active_mailbox_calendars", []))
                if n_calendars:
                    self.stdout.write(
                        f"  {user.email}: {n_calendars} mailbox calendar(s) synced"
                    )
                synced += 1
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Failed to sync mailbox ACLs for %s", user.email)
                self.stderr.write(f"  {user.email}: FAILED")
                errors += 1

        self.stdout.write(f"Done. {synced}/{total} users synced, {errors} errors.")
