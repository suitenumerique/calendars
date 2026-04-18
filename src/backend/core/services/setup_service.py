"""Service for Messages mailbox integration with CalDAV.

Handles:
- Setup: creating a principal + calendar (standalone or mailbox)
- Syncing Messages mailbox ACLs to CalDAV shares (on GET /mailboxes/)

The calendar-user-address-set is derived at runtime by PrincipalBackend
from calendarinstances shares — no explicit address sync needed.
"""

import logging

from django.conf import settings

from core.models import Organization
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


class SetupServiceError(Exception):
    """Raised when a mailbox operation fails."""


def _resolve_mailbox_org_id(mailbox_data):
    """Resolve the mailbox's organization PK from a Messages response.

    Mirrors ``backends._resolve_org_external_id``:

    - When ``OIDC_USERINFO_ORGANIZATION_CLAIM`` is configured, the
      mailbox's ``maildomain_custom_attributes`` MUST carry that claim.
      No fallback — deployments that opt into the claim want strict
      org identity and a missing claim is an error.
    - When the setting is empty, fall back to the mailbox's email
      domain so deployments without an org claim still work.

    We look up the matching ``Organization`` in our DB by ``external_id``.
    If no row exists yet (no user from that org has ever logged into
    Calendars), we auto-create one with a placeholder name — it will be
    renamed the next time a user from that org logs in via the OIDC
    backend's ``resolve_organization`` flow.

    Returns the org PK as string. Raises ``SetupServiceError`` if no
    identifier can be resolved under the active policy.
    """
    mailbox_email = mailbox_data.get("email", "")
    custom_attrs = mailbox_data.get("maildomain_custom_attributes") or {}
    org_claim = settings.OIDC_USERINFO_ORGANIZATION_CLAIM

    if org_claim:
        external_id = custom_attrs.get(org_claim)
        if not external_id:
            raise SetupServiceError(
                f"Mailbox {mailbox_email} has no "
                f"'{org_claim}' attribute on its mail domain"
            )
    else:
        external_id = (
            mailbox_email.split("@")[-1]
            if mailbox_email and "@" in mailbox_email
            else None
        )
        if not external_id:
            raise SetupServiceError(
                f"Cannot resolve organization for mailbox {mailbox_email}: "
                "no organization claim configured and no usable email domain"
            )

    org, created = Organization.objects.get_or_create(
        external_id=external_id,
        defaults={"name": f"Organization {external_id}"},
    )
    if created:
        logger.info(
            "Auto-created Organization external_id=%s for mailbox %s "
            "(name will be updated on first user login)",
            external_id,
            mailbox_email,
        )
    return str(org.id)


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

    def setup(self, user, name, mailbox_email=None, color=None):
        """Create a principal + default calendar.

        Args:
            user: The OIDC user.
            name: Display name for the calendar.
            mailbox_email: If provided, creates a MAILBOX calendar and shares
                           it with all mailbox users. If None, creates a
                           standalone INDIVIDUAL calendar.
            color: Calendar color (e.g., "#3788d8").

        Returns:
            dict with calendar_path, principal_uri, and optionally mailbox_email.

        Raises:
            SetupServiceError on failure.
        """
        if mailbox_email:
            return self._setup_mailbox(user, name, mailbox_email, color=color)
        return self._setup_standalone(user, name, color=color)

    def _setup_standalone(self, user, name, color=None):
        """Create an INDIVIDUAL principal + calendar."""
        result = self._create_calendar(
            user=user,
            email=user.email,
            name=name or user.email,
            calendar_user_type="INDIVIDUAL",
            org_id=str(user.organization_id),
            color=color,
        )
        calendar_uri = result.get("calendar_uri", "default")
        return {
            "calendar_path": f"calendars/users/{user.email}/{calendar_uri}",
            "principal_uri": f"principals/users/{user.email}",
        }

    def _setup_mailbox(self, user, name, mailbox_email, color=None):
        """Create a MAILBOX principal + calendar, shared with all mailbox users.

        Each call creates a NEW calendar under the mailbox principal so
        a single mailbox can back several calendars (e.g. ``Personal``,
        ``Triage``, ``Out-of-office`` all sending as ``me@example.com``).

        The picked ``color`` lands on the caller's own sharee instance
        only — it is never stored on the (invisible) owner row and never
        propagated to other mailbox users via the share fan-out.
        """
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

        result = self._create_calendar(
            user=user,
            email=mailbox_email,
            name=name or mailbox_email,
            calendar_user_type="MAILBOX",
            org_id=org_id,
            color=color,
            caller_email=user.email,
        )
        # ``calendar_uri`` is the owner-side URI (under the mailbox
        # principal); ``caller_calendar_uri`` is the URI the caller can
        # actually read at ``calendars/users/{user.email}/<uri>/``. The
        # response below uses the caller-side URI because the frontend
        # path it builds is read by the caller.
        caller_calendar_uri = result.get("caller_calendar_uri", "default")

        # Fan out to the rest of the mailbox users. The caller's sharee
        # row already exists (with their picked color) thanks to
        # caller_email above; sync_mailbox will leave it alone because
        # ON CONFLICT only refreshes ``access``, not ``calendarcolor``.
        self.sync_mailbox(user, mailbox_email, users=user_mailbox.get("users", []))

        return {
            "calendar_path": (f"calendars/users/{user.email}/{caller_calendar_uri}"),
            "mailbox_email": mailbox_email,
            "principal_uri": f"principals/mailboxes/{mailbox_email}",
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
            # No mailboxes — clean up any stale sync-managed shares
            try:
                self._http.internal_request(
                    "POST",
                    user,
                    "internal-api/sync-mailbox-acls/",
                    json={"shares": [], "full_sync_users": [user.email]},
                )
            except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                logger.warning("Failed to clean stale shares for user %s", user.pk)
            return {"available_mailboxes": [], "active_mailbox_calendars": []}

        role_by_email = {}
        shares = []
        for mailbox in mailboxes:
            mb_email = mailbox.get("email", "")
            mb_role = mailbox.get("role", "viewer")
            if not mb_email:
                continue
            role_by_email[mb_email] = mb_role
            # One share entry per mailbox: the CalDAV side fans it out
            # to every calendar under the mailbox principal (a single
            # mailbox can back several calendars).
            shares.append(
                {
                    "user_email": user.email,
                    "mailbox_email": mb_email,
                    "privilege": ROLE_TO_PRIVILEGE.get(mb_role, "read"),
                }
            )

        synced = self._sync_acls(user, shares, full_sync_users=[user.email])

        # ``synced`` has one entry per (user, mailbox, calendar) — the
        # PHP fan-out resolves the actual URIs, so we use those here
        # rather than assuming ``default``.
        active_calendars = [
            {
                "mailbox_email": s["mailbox_email"],
                "calendar_path": (
                    f"calendars/users/{s['mailbox_email']}/{s['calendar_uri']}"
                ),
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
            if not mb_user_email:
                continue
            # One share entry per user: the CalDAV side fans it out to
            # every calendar under the mailbox principal.
            shares.append(
                {
                    "user_email": mb_user_email,
                    "mailbox_email": mailbox_email,
                    "privilege": ROLE_TO_PRIVILEGE.get(mb_user_role, "read"),
                }
            )

        synced = self._sync_acls(caller, shares)
        return len(synced)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_calendar(  # noqa: PLR0913  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        user,
        email,
        name,
        calendar_user_type,
        org_id,
        color=None,
        caller_email=None,
    ):
        """Create a calendar (and principal if needed) via internal API.

        Returns the parsed JSON response, which includes ``calendar_uri``
        (the freshly-allocated URI under the principal — ``default`` for
        the first calendar, a UUID for subsequent ones).
        """
        payload = {
            "email": email,
            "name": name,
            "org_id": org_id,
            "calendar_user_type": calendar_user_type,
        }
        if color:
            payload["color"] = color
        if caller_email:
            payload["caller_email"] = caller_email
        try:
            resp = self._http.internal_request(
                "POST",
                user,
                "internal-api/calendars/",
                json=payload,
            )
            if resp.status_code not in (200, 201):
                raise SetupServiceError(
                    f"Failed to create calendar: {resp.status_code}"
                )
            return resp.json()
        except SetupServiceError:
            raise
        except Exception as exc:
            raise SetupServiceError(f"Failed to create calendar: {exc}") from exc

    def _sync_acls(self, caller, shares, full_sync_users=None):
        """Batch sync mailbox shares via the internal API. One call.

        Args:
            caller: User object for authenticating the internal API call.
            shares: Flat list of {user_email, mailbox_email, privilege}.
                Each entry grants access at the mailbox level — the
                CalDAV side fans it out to every owner calendar under
                the mailbox principal.
            full_sync_users: List of user emails whose stale shares should be removed.

        Returns the ``active`` list from the response: one entry per
        (user, mailbox, calendar) with the actual ``calendar_uri`` filled
        in by the fan-out.
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
