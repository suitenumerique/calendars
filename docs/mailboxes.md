# Mailbox Identity for Calendars

## Overview

Calendars can be associated with a Messages mailbox, enabling invites to be
sent/received as the mailbox email rather than the system `noreply@` address.
This is gated behind the `FEATURE_MESSAGES_INTEGRATION` feature flag.

## Key Concepts

**Two types of principals** live in the same `principals/users/` namespace:

| Type | Example | `calendar_user_type` | Created when |
|------|---------|---------------------|--------------|
| User principal | `principals/users/alice@company.com` | `INDIVIDUAL` | User creates their first calendar via setup |
| Mailbox principal | `principals/users/contact@company.com` | `MAILBOX` | User creates a mailbox calendar via setup |

**Principals** are auto-created by `PrincipalBackend` — but without a
calendar. This happens on first CalDAV access (`getPrincipalByPath`) and
when resolving a `mailto:` URI during sharing (`findByUri`). This ensures
that sharing works even if the target user hasn't opened the app yet.

**Calendars** are never auto-created. The user must go through
`POST /api/v1.0/setup/` to create their first calendar. The frontend
detects the absence of calendars and shows the setup modal.

**The Django CalDAV proxy** adds `X-LS-User: {oidc_email}` to every
request. SabreDAV uses this to authenticate the user and scope access.
A user can only read/write calendars they own or that are shared with them.

## Where Access Rights Are Stored

### User → own calendars

When a user creates a calendar, `POST /internal-api/calendars/` creates:
- A row in `principals` (the principal)
- A row in `calendarinstances` with `access=1` (owner) linking the principal
  to a new calendar

The user accesses their own calendars because the proxy sets
`X-LS-User` to their OIDC email, which matches the principal URI.

### User → shared calendars (manual sharing)

When Alice shares her calendar with Bob via the share UI, SabreDAV creates
a `calendarinstances` row:
- `principaluri = principals/users/bob@company.com`
- `calendarid` = Alice's calendar ID
- `access` = 2 (read), 3 (read-write), or higher

This is standard CalDAV sharing via `CS:share` POST. Stored entirely in
SabreDAV's `calendarinstances` table.

### User → mailbox calendars (sync-managed sharing)

When a mailbox calendar exists (e.g. `contact@company.com`), users who
have access to that mailbox in Messages need to see it. This is done via
the same `calendarinstances` sharing mechanism, but managed by
`SetupService` instead of manual user action.

**On every app open**, the frontend calls `GET /api/v1.0/setup/mailboxes/`.
Django then:

1. Queries Messages API: `GET /provisioning/mailboxes/?user_email=alice@company.com`
   → returns mailboxes Alice has access to, with her role in each AND all
   users of each mailbox (so the frontend can display who has access
   without a separate API call).

2. Builds the list of desired shares with privileges:

     | Messages role | CalDAV privilege |
     |---------------|-----------------|
     | `viewer`      | `read`          |
     | `editor`      | `read`          |
     | `sender`      | `read-write`    |
     | `admin`       | `read-write`    |

3. Calls `POST /internal-api/sync-mailbox-acls/` with `full_sync=true`
   and the full list of desired shares. The endpoint computes a diff
   against existing `sync-managed` shares and applies minimal changes:
   - Batch-fetches all owner calendar instances in one query
   - Fetches existing `sync-managed` shares for this user in one query
   - Inserts new shares, updates changed access levels, skips unchanged
   - Removes stale shares (mailboxes the user lost access to)
   - All in a single transaction

4. Returns the list of available mailboxes and which ones actually have
   calendars (`active_mailbox_calendars`) to the frontend.

**The `calendar-user-address-set` is derived automatically** by
`PrincipalBackend`: if Alice has a read-write share to a MAILBOX
calendar, that mailbox email is added to her address set at runtime.
No explicit address sync needed — the share IS the permission.

**The source of truth for mailbox access is always the Messages API.**
CalDAV shares tagged `sync-managed` are just a cache that gets refreshed
on every app open. Manual shares (with a different `share_href`) are never
touched by the sync.

**Recurring background sync**: schedule `sync_all_mailbox_acls` via cron
(or call the management command periodically). It iterates users with
organizations and resyncs their mailbox shares.

**Sync commands**:

```bash
python manage.py sync_mailbox_acls                          # all users
python manage.py sync_mailbox_acls --email alice@company.com   # one user
python manage.py sync_mailbox_acls --mailbox contact@company.com  # one mailbox
```

## Calendar Creation

All calendar creation is **explicit** — triggered by the user via the
"Create Calendar" modal. Both standalone and mailbox calendars use the
same endpoint: `POST /api/v1.0/setup/`.

### Onboarding flow

1. User logs in via OIDC (e.g. `alice@company.com`). No CalDAV principal
   or calendar exists yet.
2. Frontend calls `GET /api/v1.0/setup/mailboxes/`. Django queries Messages
   API to get the list of mailboxes Alice has access to. This may include:
   - Her own email as a personal mailbox (`alice@company.com`, role=sender)
   - Team mailboxes (`contact@company.com`, role=admin)
   - Or nothing, if Messages integration is disabled or she has no mailboxes
3. Frontend detects the user has no calendars → shows the creation modal
   in onboarding mode (`isOnboarding=true`).
4. The modal shows a mailbox selector dropdown populated from step 2.
   If the user has no mailboxes, the selector is hidden and the user can
   only create a standalone calendar.
5. User fills in the calendar name and optionally selects a mailbox.
6. Frontend calls `POST /api/v1.0/setup/`:
   - **`{"name": "My Calendar"}`** → Django creates an INDIVIDUAL principal
     + default calendar under `calendars/users/alice@company.com/default`.
   - **`{"name": "Contact Team", "mailbox_email": "contact@company.com"}`**
     → Django verifies Alice has sender/admin access, then creates a MAILBOX
     principal + calendar under `calendars/users/contact@company.com/default`.
     Shares are created lazily: other users pick up the new calendar on
     their next `GET /setup/mailboxes/` call.

Note: a user who selects a personal mailbox (`alice@company.com`) gets
the same principal URI as a standalone calendar — the only difference is
`calendar_user_type=MAILBOX`, which makes invitations go through Messages
API instead of SMTP.

## Calendar Sharing

Two sharing mechanisms coexist:

### Who do we share with?

Always with **OIDC user principals** (`principals/users/{oidc_email}`).
The sharee must have a principal that matches their `X-LS-User`
header for them to see the shared calendar.

Mailbox principals are never sharees — they are always owners. A mailbox
principal owns the calendar; OIDC user principals get shares to it.

### Manual sharing (user-initiated)

Works the same as any CalDAV sharing. Alice opens the share modal, picks
Bob, sets a privilege. The frontend sends a `CS:share` POST to SabreDAV.
Stored in `calendarinstances`. Not managed by sync — persists until
manually removed.

**For mailbox calendars, manual shares are read-only.** To grant someone
read-write access (which also grants the ability to send invitations as
the mailbox), that must be done in Messages by giving them `sender` or
`admin` role on the mailbox. The sync will then create the read-write
CalDAV share automatically. This ensures Messages remains the single
source of truth for who can send as a mailbox.

### Share modal behavior for mailbox calendars

The share modal detects mailbox calendars and adapts its UI:

- **Sync-managed shares** (users from Messages): role dropdown is locked
  to the current role (single option). Delete button is hidden. A hint
  message says "Managed by Messages. Change permissions in Messages."
  The frontend identifies sync-managed shares by cross-referencing the
  sharee email against the `users` array in the mailbox data.

- **New invitations**: only `freebusy` and `read` roles are available
  (no `read-write` or `admin`). This is enforced both in the frontend
  (restricted role list) and in SabreDAV (`MailboxPlugin`
  rejects `CS:share` with access > read on MAILBOX calendars).

- **Manual shares**: can be freely edited and deleted by the user.

- **Sync takes over manual shares**: if a user has a manual read-only
  share and is later added in Messages with `sender` role, the next
  sync upserts the `calendarinstances` row (matching on
  `principaluri + calendarid`), upgrading it to read-write and setting
  `is_sync_managed = TRUE`. The manual share is effectively replaced.

### Mailbox sharing (sync-managed)

Shares are synced in two directions:
- **On mailbox calendar creation**: `SetupService.sync_mailbox()` creates
  shares for all users immediately. The user list comes from the `users`
  field already included in the Messages mailbox response (no extra call).
- **On each user's app open**: `GET /setup/mailboxes/` syncs that user's
  shares (picks up new mailbox calendars, updates changed roles, removes
  stale shares). Again, one Messages API call returns everything.

All sync-managed shares are tagged with `is_sync_managed = TRUE`
in `calendarinstances`. This distinguishes them from manual shares and
allows the sync to cleanly add/update/remove its own shares without
touching user-created ones.

### Restriction on MAILBOX calendar sharing

`MailboxPlugin` enforces that native `CS:share` POST
requests (i.e. manual sharing from the UI or CalDAV clients) can only
grant **read-only** access to MAILBOX calendars. Write access must come
through the Messages ACL sync (which uses the internal API and bypasses
this restriction). This ensures Messages remains the single source of
truth for who can send as a mailbox.

## Invitations

### Standalone calendar (INDIVIDUAL principal)

Standard flow. SabreDAV's Schedule plugin fires the iMIP callback.
`CalendarInvitationService` sends via SMTP from `noreply@`.

### Mailbox calendar (MAILBOX principal)

1. User creates an event in a mailbox calendar.
2. Frontend sets `ORGANIZER = mailto:{mailbox_email}`. This works because
   the mailbox email is in the user's `calendar-user-address-set`
   (derived by `PrincipalBackend` from the read-write share).
3. CalDAV PUT goes through the proxy with `X-LS-User: {oidc_email}`.
4. SabreDAV's Schedule plugin validates ORGANIZER is in the user's
   address set → OK.
5. `HttpCallbackIMipPlugin` checks the sender's principal type in the DB
   and sends the `X-LS-Is-Mailbox: true` header along with the
   callback to Django.
6. `CalDAVSchedulingCallbackView` reads the header — no extra API call.
7. `CalendarInvitationService` composes a MIME message and submits it to
   Messages via `POST /api/v1.0/submit/` (raw RFC 5322, DKIM-signed by
   Messages). No SMTP fallback — mailbox invitations must come from the
   mailbox identity or not at all.

### RSVP

When an attendee clicks the RSVP link, the handler needs to find and
update the event in CalDAV. The organizer email from the signed RSVP
token is used as `X-LS-User` to authenticate the CalDAV request.
This works for both regular users and mailbox principals — the token's
`organizer` field always matches the principal URI that owns the event.

## Internal API Endpoints (CalDAV side)

All in `InternalApiPlugin.php`. Authenticated via `X-LS-Internal-Api-Key`.
Not accessible from the outside (blocked by Django proxy).

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/internal-api/calendars/` | Create a calendar (and principal if needed) |
| `POST` | `/internal-api/sync-mailbox-acls/` | Sync Messages ACL shares for one user |
| `POST` | `/internal-api/resources/` | Create a resource principal |
| `DELETE` | `/internal-api/resources/{id}` | Delete a resource principal |

### `POST /internal-api/calendars/` vs MKCALENDAR

Two ways to create calendars exist for different use cases:

| | MKCALENDAR | `POST /internal-api/calendars/` |
|---|---|---|
| Auth | `X-LS-User` (OIDC user) | `X-LS-Internal-Api-Key` (server-to-server) |
| Creates principal | No (must exist) | Yes (upsert) |
| Sets `calendar_user_type` | No | Yes |
| Calendar owner | The authenticated user | Any email (including mailbox) |
| Calendar URI | User chooses | Always `default` |
| Use case | Adding a 2nd/3rd calendar | Setup (first calendar, or mailbox calendar) |

MKCALENDAR can't create mailbox calendars because the user is authenticated
as their OIDC email but needs to create a calendar under a different
principal. The internal API bypasses this restriction.

`POST /internal-api/calendars/` accepts:
```json
{
  "email": "contact@company.com",
  "name": "Contact Team",
  "org_id": "org-uuid",
  "calendar_user_type": "INDIVIDUAL|MAILBOX"
}
```
Safe to call repeatedly — upserts the principal, creates the calendar
only if none exists.

`POST /internal-api/sync-mailbox-acls/` accepts:
```json
{
  "shares": [
    {"user_email": "alice@co", "mailbox_email": "contact@co",
     "calendar_uri": "default", "privilege": "read-write"},
    {"user_email": "bob@co", "mailbox_email": "contact@co",
     "calendar_uri": "default", "privilege": "read"}
  ],
  "full_sync_users": ["alice@co"]
}
```
`shares` is a flat list of all desired `sync-managed` shares across
multiple users. `full_sync_users` lists which users should have stale
shares removed (users not in the list only get additive upserts).
Batch-fetches owner calendars and existing shares in two queries,
computes diff, applies minimal writes in one transaction.

## Django API Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v1.0/setup/mailboxes/` | OIDC | List user's mailboxes (with users) + sync shares |
| `POST` | `/api/v1.0/setup/` | OIDC | Create a calendar (standalone or mailbox) |

`GET /api/v1.0/setup/mailboxes/` fetches the user's mailboxes from Messages
(cached 5 min) and syncs CalDAV shares as a side effect. Each mailbox
includes a `users` array with all users who have access. Returns both
`available_mailboxes` and `active_mailbox_calendars`. One API call to
Messages — no N+1.

`POST /api/v1.0/setup/` accepts:
- `{"name": "My Calendar"}` → standalone calendar (INDIVIDUAL principal)
- `{"name": "Contact", "mailbox_email": "contact@co"}` → mailbox calendar

## Organizations

Mailbox principals need an `org_id` for org-scoped features (freebusy
visibility, principal discovery). The org is resolved from the **mailbox's
mail domain**, not from the creating user:

1. The Messages provisioning API is called with
   `add_maildomain_custom_attributes={OIDC_USERINFO_ORGANIZATION_CLAIM}`.
2. The response includes `maildomain_custom_attributes: {<claim>: <value>}`
   (e.g. `{"siret": "12345678900010"}`).
3. `SetupService._resolve_mailbox_org_id` calls
   `Organization.objects.get_or_create(external_id=value, defaults=...)`
   and assigns that org's ID to the mailbox principal.

This ensures the mailbox principal belongs to the correct organization
regardless of which user creates it. If no `Organization` row exists yet
(no user from that org has logged into Calendars), one is auto-created
with `name = "Organization {external_id}"` as a placeholder; the OIDC
backend's `resolve_organization` will overwrite the name with the real
one the next time a user from that org logs in.

If `OIDC_USERINFO_ORGANIZATION_CLAIM` is not configured or the mailbox's
mail domain has no value for that claim, mailbox calendar creation
**fails with a `SetupServiceError`** — there is no silent fallback to
the creator's organization, since that would silently break cross-org
isolation for freebusy and discovery.

For standalone (INDIVIDUAL) calendars, `org_id` comes from the creating
user's organization as before.

## Configuration

```bash
FEATURE_MESSAGES_INTEGRATION=true   # Feature flag
MESSAGES_API_URL=http://messages:8000  # Messages app API URL
MESSAGES_API_KEY=<shared-secret>      # Sent as X-Service-Auth header
```

On the Messages side, the same secret is configured as `CALENDARS_API_KEY`.
