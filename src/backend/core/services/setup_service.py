"""Service for Messages mailbox integration with CalDAV.

Handles:
- Setup: creating a principal + calendar (standalone or mailbox)
- Syncing Messages mailbox ACLs to CalDAV shares (on GET /mailboxes/)

The calendar-user-address-set is derived at runtime by PrincipalBackend
from calendarinstances shares — no explicit address sync needed.
"""

import json
import logging

from django.conf import settings

from core.services.caldav_service import CalDAVHTTPClient
from core.services.messages_service import MessagesService

logger = logging.getLogger(__name__)

# Messages role → CalDAV share privilege
ROLE_TO_PRIVILEGE = {
    "viewer": "read",
    "editor": "read",
    "sender": "read-write",
    "admin": "read-write",
}

# Roles that allow sending invites as the mailbox
SEND_ROLES = {"sender", "admin"}


def _resolve_mailbox_org_id(mailbox_data):
    """Extract org external_id from a Messages mailbox response.

    Messages returns maildomain_custom_attributes containing the org claim
    (e.g. SIRET). We look up the matching Organization in our DB.
    Returns the org PK as string, or None.
    """
    custom_attrs = mailbox_data.get("maildomain_custom_attributes", {})
    org_claim = settings.OIDC_USERINFO_ORGANIZATION_CLAIM
    if not org_claim or not custom_attrs:
        return None

    external_id = custom_attrs.get(org_claim)
    if not external_id:
        return None

    from core.models import Organization  # noqa: PLC0415

    try:
        org = Organization.objects.get(external_id=external_id)
        return str(org.id)
    except Organization.DoesNotExist:
        logger.warning(
            "Organization with external_id=%s not found for mailbox %s",
            external_id,
            mailbox_data.get("email", ""),
        )
        return None


class SetupServiceError(Exception):
    """Raised when a mailbox operation fails."""


class SetupService:
    """Manages the link between Messages mailboxes and CalDAV calendars."""

    def __init__(self):
        self._http = CalDAVHTTPClient()
        self._messages = None

    @property
    def messages(self):
        """Lazy-init Messages client (only needed for mailbox operations)."""
        if self._messages is None:
            self._messages = MessagesService()
        return self._messages

    # ------------------------------------------------------------------
    # Setup: POST /api/v1.0/setup/
    # ------------------------------------------------------------------

    def setup(self, user, name, mailbox_email=None):
        """Create a principal + default calendar.

        Args:
            user: The OIDC user.
            name: Display name for the calendar.
            mailbox_email: If provided, creates a MAILBOX calendar and shares
                           it with all mailbox users. If None, creates a
                           standalone INDIVIDUAL calendar.

        Returns:
            dict with calendar_path, principal_uri, and optionally mailbox_email.

        Raises:
            SetupServiceError on failure.
        """
        if mailbox_email:
            return self._setup_mailbox(user, name, mailbox_email)
        return self._setup_standalone(user, name)

    def _setup_standalone(self, user, name):
        """Create an INDIVIDUAL principal + default calendar."""
        self._create_calendar(
            user=user,
            email=user.email,
            name=name or user.email,
            calendar_user_type="INDIVIDUAL",
        )
        return {
            "calendar_path": f"calendars/users/{user.email}/default",
            "principal_uri": f"principals/users/{user.email}",
        }

    def _setup_mailbox(self, user, name, mailbox_email):
        """Create a MAILBOX principal + default calendar, shared with all users."""
        if not settings.FEATURE_MESSAGES_INTEGRATION:
            raise SetupServiceError("Messages integration is not enabled")

        # Verify user has sender/admin access
        mailboxes = self.messages.get_user_mailboxes(user.email)
        user_mailbox = next(
            (mb for mb in mailboxes if mb.get("email") == mailbox_email),
            None,
        )
        if not user_mailbox:
            raise SetupServiceError(
                f"User {user.email} does not have access to mailbox {mailbox_email}"
            )

        user_role = user_mailbox.get("role", "viewer")
        if user_role not in SEND_ROLES:
            raise SetupServiceError(
                f"User needs 'sender' or 'admin' role to create a mailbox calendar"
                f" (current role: {user_role})"
            )

        # Resolve org from the mailbox's mail domain custom attributes
        org_id = _resolve_mailbox_org_id(user_mailbox)

        self._create_calendar(
            user=user,
            email=mailbox_email,
            name=name or mailbox_email,
            calendar_user_type="MAILBOX",
            org_id=org_id,
        )

        # Share with all mailbox users immediately (users already in the response)
        self.sync_mailbox(user, mailbox_email, users=user_mailbox.get("users", []))

        return {
            "calendar_path": f"calendars/users/{mailbox_email}/default",
            "mailbox_email": mailbox_email,
            "principal_uri": f"principals/users/{mailbox_email}",
        }

    # ------------------------------------------------------------------
    # Sync: GET /api/v1.0/mailboxes/
    # ------------------------------------------------------------------

    def sync_user_mailboxes(self, user):
        """Sync Messages mailbox ACLs for this user.

        One Messages API call, one internal API call. Returns dict with:
            available_mailboxes: list of mailboxes the user has access to
            active_mailbox_calendars: list of mailbox calendar paths shared
        """
        if not settings.FEATURE_MESSAGES_INTEGRATION:
            return {"available_mailboxes": [], "active_mailbox_calendars": []}

        mailboxes = self.messages.get_user_mailboxes(user.email)
        if not mailboxes:
            return {"available_mailboxes": [], "active_mailbox_calendars": []}

        role_by_email = {}
        shares = []
        for mailbox in mailboxes:
            mb_email = mailbox.get("email", "")
            mb_role = mailbox.get("role", "viewer")
            if not mb_email:
                continue
            role_by_email[mb_email] = mb_role
            shares.append(
                {
                    "user_email": user.email,
                    "mailbox_email": mb_email,
                    "calendar_uri": "default",
                    "privilege": ROLE_TO_PRIVILEGE.get(mb_role, "read"),
                }
            )

        synced = self._sync_acls(user, shares, full_sync_users=[user.email])

        active_calendars = [
            {
                "mailbox_email": s["mailbox_email"],
                "calendar_path": f"calendars/users/{s['mailbox_email']}/default",
                "role": role_by_email.get(s["mailbox_email"], "viewer"),
            }
            for s in synced
        ]

        return {
            "available_mailboxes": mailboxes,
            "active_mailbox_calendars": active_calendars,
        }

    # ------------------------------------------------------------------
    # Sync from mailbox side: for all users of a given mailbox
    # ------------------------------------------------------------------

    def sync_mailbox(self, caller, mailbox_email, users=None):
        """Sync shares for all users of a mailbox. One internal API call.

        Args:
            caller: A user object for authenticating internal API calls.
            mailbox_email: The mailbox email to sync.
            users: Optional list of {"email", "role"} dicts. If not provided,
                   fetched from Messages via get_mailbox_by_email().

        Returns:
            Number of shares synced.
        """
        if users is None:
            mailbox = self.messages.get_mailbox_by_email(mailbox_email)
            users = mailbox.get("users", []) if mailbox else []

        shares = []
        for mb_user in users:
            mb_user_email = mb_user.get("email", "")
            mb_user_role = mb_user.get("role", "viewer")
            if not mb_user_email or mb_user_email == mailbox_email:
                continue
            shares.append(
                {
                    "user_email": mb_user_email,
                    "mailbox_email": mailbox_email,
                    "calendar_uri": "default",
                    "privilege": ROLE_TO_PRIVILEGE.get(mb_user_role, "read"),
                }
            )

        synced = self._sync_acls(caller, shares)
        return len(synced)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_calendar(self, user, email, name, calendar_user_type, org_id=None):
        """Create a calendar (and principal if needed) via internal API."""
        if org_id is None:
            org_id = str(user.organization_id) if user.organization_id else None
        try:
            resp = self._http.internal_request(
                "POST",
                user,
                "internal-api/calendars/",
                json={
                    "email": email,
                    "name": name,
                    "org_id": org_id,
                    "calendar_user_type": calendar_user_type,
                },
            )
            if resp.status_code not in (200, 201):
                raise SetupServiceError(
                    f"Failed to create calendar: {resp.status_code}"
                )
        except SetupServiceError:
            raise
        except Exception as exc:
            raise SetupServiceError(f"Failed to create calendar: {exc}") from exc

    def _sync_acls(self, caller, shares, full_sync_users=None):
        """Batch sync mailbox shares via the internal API. One call.

        Args:
            caller: User object for authenticating the internal API call.
            shares: Flat list of {user_email, mailbox_email, calendar_uri, privilege}.
            full_sync_users: List of user emails whose stale shares should be removed.

        Returns list of shares that were actually created.
        """
        try:
            resp = self._http.internal_request(
                "POST",
                caller,
                "internal-api/sync-mailbox-acls/",
                json={
                    "shares": shares,
                    "full_sync_users": full_sync_users or [],
                },
            )
            if resp.status_code == 200:
                return resp.json().get("active", [])
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to sync mailbox ACLs")
        return []
