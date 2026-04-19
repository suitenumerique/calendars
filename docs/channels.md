# Channels

Channels provide external services (e.g.
[Messages](https://github.com/suitenumerique/messages)) with authenticated
access to the CalDAV server. The design mirrors the
[Messages Channel model](https://github.com/suitenumerique/messages) so the
two services use the same vocabulary and patterns.

See also the Messages implementation:
[`ChannelScopeLevel` / `ChannelApiKeyScope` enums](https://github.com/suitenumerique/messages/blob/main/src/backend/core/enums.py).

## Authentication

Channels authenticate via **HTTP Basic Auth**, which is the standard
CalDAV authentication mechanism. This means any CalDAV client library
(python-caldav, tsdav, Apple Calendar, Thunderbird, ...) works out of the
box:

```http
Authorization: Basic base64(<user_email>:<channel_id><channel_token>)
```

- **username** = user email (enables standard CalDAV principal discovery)
- **password** = `<channel_id><channel_token>` — the base64url-encoded
  channel id (fixed 22 chars) immediately followed by the token, with
  **no separator**.

Using the user's email as the Basic Auth username means CalDAV principal
discovery works naturally: the server returns the correct
`current-user-principal` without any custom headers.

For `user`/`calendar`-scoped channels, the proxy verifies the email
matches `channel.user.email`. For `global` channels, the email determines
which user the channel acts as.

The Django CalDAV proxy (`CalDAVProxyView`) parses the Basic Auth header,
verifies the token, and translates to internal `X-LS-*` headers before
forwarding to SabreDAV. The `X-LS-*` namespace is strictly internal
between Django and SabreDAV and is never exposed to external clients.

## Scope levels

Every channel has a `scope_level` that determines which CalDAV resources
it can access. This mirrors Messages' `ChannelScopeLevel`.

| `scope_level` | Target FKs | Access | Created via |
|---|---|---|---|
| `global` | none required | Any user's calendars | Django admin / CLI only |
| `user` | `user` (required) | That user's calendars | API or admin |
| `calendar` | `user` + `caldav_path` (required) | One specific calendar | API or admin |

A DB check constraint (`channel_scope_level_targets`) enforces the FK
invariants at the database level.

### Global channels and user derivation

For `scope_level=global` channels, the acting user is determined by the
**email in the Basic Auth username**. The proxy looks up the User in the
database to obtain `organization_id` for org-scoped enforcement in
SabreDAV.

This keeps the integration maximally CalDAV-compatible: the external
service authenticates as the target user via standard Basic Auth, and
CalDAV principal discovery works naturally.

### Example: Messages integration

Messages creates **one global channel** (via Django admin or management
command) and stores the channel ID and token in its environment config.
To access a user's calendars:

```python
import caldav

client = caldav.DAVClient(
    url="https://calendar.example.com/caldav/",
    username=user_email,
    password=f"{CHANNEL_ID}{CHANNEL_TOKEN}",
)
# Standard CalDAV principal discovery works
principal = client.principal()
calendars = principal.calendars()
```

This mirrors how Calendars calls Messages: one API key, one channel,
act on behalf of any user.

## Scopes

Channels use a **scopes array** (stored in `settings.scopes`) instead of
a single role. Each scope grants access to a set of CalDAV HTTP methods
that can be enforced at the protocol level (path + HTTP method) without
deep XML or iCal inspection.

### Active scopes

| Scope | HTTP methods | Purpose |
|---|---|---|
| `calendars:read` | PROPFIND, OPTIONS | List/discover calendars (collection metadata) |
| `events:read` | GET, REPORT, OPTIONS | Read event data, date-range queries, free-busy |
| `events:write` | PUT, DELETE, POST | Create, update, delete events |
| `calendars:write` | MKCALENDAR, MKCOL, PROPPATCH, DELETE | Create, manage, delete calendars |

A channel can have multiple scopes. For example, a Messages integration
channel would typically have
`["calendars:read", "events:read", "events:write"]` — it needs to
discover calendars, check conflicts, and add/update events, but not
create or delete calendars.

### Design principle

Scopes are designed to be **enforceable at the CalDAV protocol level**
using only the HTTP method and path, without requiring deep inspection of
the XML request body or iCal content. This keeps the proxy thin and fast,
and avoids coupling scope enforcement to CalDAV protocol internals.

For example, `events:write` grants PUT (which is how CalDAV creates and
updates events) and DELETE (which removes events). The proxy checks the
HTTP method against the channel's allowed methods — it does not need to
parse the VCALENDAR body to determine intent.

### Future scopes (not yet active)

These scopes are planned but not yet wired to enforcement endpoints.
They follow the same `resource:action` naming convention:

| Scope | Purpose |
|---|---|
| `resources:read` | Read resource calendars (rooms, equipment) |
| `resources:write` | Book and manage resource calendars |
| `freebusy:read` | Query free-busy information |
| `scheduling:write` | Send iTIP scheduling messages (invitations, replies) |

### Global-only scopes

Some scopes are restricted to `scope_level=global` channels. Currently:

- `calendars:write` — creating or deleting calendars is an admin-level
  operation that should only be available to trusted service integrations.

This mirrors Messages' `CHANNEL_API_KEY_SCOPES_GLOBAL_ONLY` pattern.

## Immutability

`PATCH /api/v1.0/channels/{id}/` can modify a limited set of fields:

- **Updatable**: `name`, `is_active`, `scopes`
- **Immutable after creation**: `scope_level`, `caldav_path`, `type`,
  `user`, `organization`

This is a security invariant: changing `scope_level` from `user` to
`global` would be a privilege escalation, and changing `caldav_path`
would grant access to a different calendar. To change any immutable
field, delete the channel and create a new one.

## Access control: two layers

Channel scopes are an **upper bound** on what HTTP methods the proxy
allows. The actual access control is enforced by **SabreDAV's ACL
system** at runtime, not at channel creation time.

For example, if a user creates a channel with `events:write` scope on a
shared calendar they can only read:
1. The proxy allows PUT (channel has `events:write` scope)
2. SabreDAV receives the request with `X-LS-User` = the user's email
3. SabreDAV checks the user's ACL on the calendar
4. SabreDAV returns 403 (user only has read access)

This means scopes don't grant access beyond what SabreDAV allows — they
only restrict the proxy's forwarding. Write access is always enforced
at runtime by SabreDAV, not checked at channel creation time.

## Channel lifecycle

1. **Creation**: via the `/api/v1.0/channels/` endpoint (user/calendar
   scope) or Django admin / management command (global scope). The token
   is returned exactly once on creation. Global channels cannot be
   created via the API.

2. **Token rotation**: `POST /api/v1.0/channels/{id}/regenerate-token/`
   rotates the token. The old token is immediately invalidated.

3. **Deactivation**: set `is_active=False` to disable without deleting.

4. **Audit**: every CalDAV write through a channel includes the channel
   ID in `X-LS-Channel-Id` for audit tracking. Events created via a
   channel can be listed and bulk-deleted via the channel events API.

## Migration from roles

The previous role-based system (`reader`/`editor`/`admin`) is replaced by
scopes. The mapping is:

| Old role | New scopes |
|---|---|
| `reader` | `["calendars:read", "events:read"]` |
| `editor` | `["calendars:read", "events:read", "events:write"]` |
| `admin` | `["calendars:read", "events:read", "events:write", "calendars:write"]` |

Migration `0003_channel_scope_level` handles the data conversion
automatically.
