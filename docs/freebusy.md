# Freebusy-Only Calendar Shares

## TL;DR

There is **no standard CalDAV way to express "freebusy only" sharing**.
We implement it as a `CS:read` share with a custom `LS:share-access`
property and server-side content stripping. This gives users a persistent
calendar subscription that shows busy blocks — better UX than on-demand
scheduling queries.

## Why Our Approach Is Better

| | On-demand freebusy (Apple/RFC 6638) | Persistent freebusy share (ours) |
|---|---|---|
| Calendar in sidebar | No | Yes |
| See busy blocks in week view | No (only during scheduling) | Yes |
| Works with all CalDAV clients | Yes (if client supports VFREEBUSY) | Yes (server strips details) |
| Standards-compliant | Yes | Partially (CS:read + custom extension) |
| Requires explicit query | Yes (POST to outbox) | No (syncs like any calendar) |

Apple Calendar only shows freebusy during the "Find a time" meeting
scheduler. There's no way to persistently subscribe to someone's
availability as a calendar. Our approach adds a real calendar entry
that shows busy blocks — the user sees it in their sidebar alongside
their own calendars.

## Standards Landscape

### Is There a Standard Freebusy Share Level?

**No.** After researching all relevant specs and implementations:

- [Apple CalendarServer sharing spec](https://github.com/apple/ccs-calendarserver/blob/master/doc/Extensions/caldav-sharing.txt):
  only `CS:read` and `CS:read-write`. No `CS:freebusy`.
- [draft-pot-caldav-sharing](https://datatracker.ietf.org/doc/html/draft-pot-caldav-sharing-01)
  (expired IETF draft): no freebusy access level.
- [RFC 4791](https://www.rfc-editor.org/rfc/rfc4791): defines `CALDAV:read-free-busy`
  as an ACL privilege for query access, not a sharing level.
- [RFC 6638](https://www.rfc-editor.org/rfc/rfc6638.html): defines scheduling-based
  freebusy queries (outbox POST), not persistent shares.
- SabreDAV, Nextcloud, Radicale, Baikal: none implement freebusy shares.
- [Nextcloud feature request](https://github.com/nextcloud/server/issues/11214):
  open since 2018, no implementation.

### Two Standard Freebusy Mechanisms (Neither Is Sharing)

**1. `CALDAV:free-busy-query REPORT` (RFC 4791)**

A REPORT request on a calendar collection. Returns `VFREEBUSY` blocks.
Gated by `CALDAV:read-free-busy` privilege. SabreDAV grants this to all
authenticated users by default.

- **Limitation**: On-demand query, not a persistent subscription. The
  client must explicitly run the REPORT. No calendar appears in the sidebar.

**2. Scheduling Outbox VFREEBUSY (RFC 6638)**

An organizer POSTs a `VFREEBUSY` request to their scheduling outbox.
The server checks the attendee's inbox for `CALDAV:schedule-deliver`
privilege and returns availability.

- **Limitation**: Only works during meeting scheduling ("Find a time").
  Requires the organizer to know the attendee's calendar user address.
  No persistent access.

### How Apple Does It

Apple uses scheduling (RFC 6638) for freebusy — not sharing. In macOS/iOS
Calendar's "Find a time" panel, a `VFREEBUSY` request is sent via the
outbox. There is no "freebusy-only calendar share" concept in Apple's
model.

### Why Not CS:summary?

The CalendarServer sharing spec defines `CS:summary` as a human-readable
description field for shared calendars:

> "A brief description of a shared calendar. This can be used by sharers
> to communicate the nature of a shared calendar to sharees."

An earlier iteration of our implementation stored `access:freebusy` as the
`CS:summary` value. This works but abuses a human-readable field with a
machine-readable marker. If a future CalDAV client (Apple Calendar,
Thunderbird, DAVx5) starts displaying `CS:summary` in the UI, users would
see `"access:freebusy"` as the share description.

We now use a **proper custom CalDAV extension** in our own namespace instead.

## Implementation: Custom CalDAV Extension

### Namespace and Properties

We define a CalDAV extension in the **La Suite namespace**:

```text
{http://lasuite.numerique.gouv.fr/ns/}  (abbreviated LS:)
```

Two custom properties:

| Property | On | Purpose |
|---|---|---|
| `LS:share-access` | Sharee's calendar instance | The sharee's access level (e.g., `"freebusy"`) |
| `LS:share-access-map` | Owner's calendar | Map of all sharee hrefs → access levels |

### Protocol Flow

**1. Setting a freebusy share** — CS:share POST with `LS:share-access`:

```xml
<CS:share xmlns:D="DAV:"
          xmlns:CS="http://calendarserver.org/ns/"
          xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">
  <CS:set>
    <D:href>mailto:alice@example.com</D:href>
    <LS:share-access>freebusy</LS:share-access>
    <CS:read/>
  </CS:set>
</CS:share>
```

The `CS:read` access level is standard CalDAV. The `LS:share-access`
element is our extension that the `ShareAccessPlugin` persists.

**2. Reading the access level** — PROPFIND on the sharee's instance:

```xml
<D:propfind xmlns:D="DAV:"
            xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">
  <D:prop>
    <LS:share-access/>
  </D:prop>
</D:propfind>
```

Returns `<LS:share-access>freebusy</LS:share-access>` or 404 (not set).

**3. Owner's sharing UI** — PROPFIND with `LS:share-access-map`:

```xml
<D:propfind xmlns:D="DAV:"
            xmlns:LS="http://lasuite.numerique.gouv.fr/ns/">
  <D:prop>
    <LS:share-access-map/>
  </D:prop>
</D:propfind>
```

Returns all sharees with non-default access levels:

```xml
<LS:share-access-map>
  <LS:sharee href="mailto:alice@example.com" access="freebusy"/>
</LS:share-access-map>
```

### ShareAccessPlugin

SabreDAV plugin that implements the extension:

1. `beforeMethod:POST` (priority 50) — caches the CS:share body before
   SabreDAV consumes the stream
2. `afterMethod:POST` (priority 200) — parses the XML, extracts
   `LS:share-access` values, and saves them to `share_access_level`
   on the corresponding `calendarinstances` row
3. `propFind` (priority 200) — exposes `LS:share-access` on the sharee's
   calendar instance and `LS:share-access-map` on the owner's calendar

### SharedCalendarPrivacyPlugin

Enforces freebusy privacy server-side:

- Detects `share_access_level = 'freebusy'` on the sharee's calendar instance
- Replaces `SUMMARY`, `DESCRIPTION`, `LOCATION`, `ATTENDEE` etc.
  with `SUMMARY:Busy` on PROPFIND/GET responses
- Applies `CLASS:CONFIDENTIAL` treatment regardless of the event's
  actual `CLASS` value
- Blocks COPY from freebusy calendars (prevents data exfiltration)
- Strips VALARM components for all non-owner sharees

This means **all CalDAV clients see busy blocks**, not event details.
No client-side logic needed.

### Storage

Column on `calendarinstances`:

```sql
share_access_level VARCHAR(50)  -- NULL for normal shares, 'freebusy' for freebusy-only
```

### Frontend

```typescript
// CS:share POST includes LS:share-access for freebusy shares
<LS:share-access>freebusy</LS:share-access>

// parseSharePrivilege reads from LS:share-access-map PROPFIND
function parseSharePrivilege(access, shareAccess?: string): SharePrivilege {
  if (shareAccess === 'freebusy') return 'freebusy'
  // ... standard access parsing
}
```

The frontend reads `LS:share-access-map` alongside `CS:invite` in a single
PROPFIND to distinguish freebusy from read shares in the sharing modal.

## Client Compatibility

| Client | Calendar visible? | Event details? | Freebusy blocks? |
|--------|------------------|----------------|------------------|
| Our frontend | Yes | No (stripped) | Yes |
| Apple Calendar (macOS/iOS) | Yes | No (stripped) | Yes (shows "Busy") |
| Thunderbird | Yes | No (stripped) | Yes (shows "Busy") |
| DAVx5 (Android) | Yes | No (stripped) | Yes |
| Nextcloud | Yes | No (stripped) | Yes |
| Outlook CalDAV Sync | Yes | No (stripped) | Yes |

All clients work because the server does the work. No client needs to
understand `LS:share-access` — they just see events with `SUMMARY:Busy`
and no details. The custom property is only used by our frontend to show
the correct label in the sharing UI.

## Calendar-Level Transparency (RFC 6638)

### `CALDAV:schedule-calendar-transp`

Standard CalDAV property (RFC 6638) that controls whether a calendar's
events count toward freebusy calculations:

| Value | Meaning | Use case |
|---|---|---|
| `opaque` (default) | Events count as busy | Work calendars, meetings |
| `transparent` | Events don't count | Birthdays, holidays, FYI calendars |

This is a per-calendar-instance property — each user controls their own
view. If someone shares a birthday calendar, the sharee can mark it
transparent on their side without affecting the owner's setting.

### UI

The "Include in availability" checkbox in the calendar edit modal
toggles this property via PROPPATCH. Default is checked (opaque).

Apple Calendar exposes this as "Show in availability" in calendar
settings. Thunderbird and DAVx5 also support it natively.

## Future: Intermediate Access Levels

### `share_access_level` Column Design

The `share_access_level` column is `VARCHAR(50)` (not boolean) to
support future intermediate access levels between freebusy and full-read:

| Value | Shows | Hides | Precedent |
|---|---|---|---|
| `freebusy` (current) | Time blocks only | Everything | Google "See only free/busy" |
| `titles` (future) | SUMMARY + LOCATION | DESCRIPTION, ATTENDEE, CONFERENCE | Exchange "FreeBusyTimeAndSubjectAndLocation" |
| NULL (default) | Full read per CalDAV access level | Nothing | Standard CS:read |

The `titles` level would be trivially implemented by adding `SUMMARY`
and `LOCATION` to the `SharedCalendarPrivacyPlugin` whitelist.

### Per-Event Attendee Visibility (Future)

A separate but related concept: hiding the attendee list on individual
events. When an organizer creates a 50-person event, they might not
want every attendee to see all other attendees.

Google Calendar has `guestsCanSeeOtherGuests` for this. In CalDAV,
this would be a per-event property (not per-share) enforced during
iTIP message delivery — stripping ATTENDEE properties from outgoing
scheduling messages. This is architecturally different from per-share
access levels (different layer, different enforcement point).

## Organization-Level Freebusy Controls

### `FreeBusyOrgScopePlugin`

Enforces `effective_sharing_level` from the Django Organization model:

| `effective_sharing_level` | Outbox VFREEBUSY | free-busy-query REPORT (same-org) | free-busy-query REPORT (cross-org) |
|---|---|---|---|
| `none` | Blocked | Blocked | Blocked |
| `freebusy` | Allowed | Allowed (returns busy blocks) | Blocked |
| `read` | Allowed | Allowed | Blocked |
| `write` | Allowed | Allowed | Blocked |

Cross-org is always blocked regardless of sharing level. The plugin reads
`X-LS-Org-Sharing-Level` and `X-LS-Org-Id` headers set by the
Django proxy, and checks the target calendar owner's `org_id` in the
`principals` table.

### Freebusy via Scheduling Outbox

RFC 6638 scheduling freebusy (POST to outbox) works independently of
sharing. This is the "Find a time" feature. Both coexist with our
freebusy shares.

## References

- [RFC 4791 — CalDAV](https://www.rfc-editor.org/rfc/rfc4791) — `CALDAV:read-free-busy`
- [RFC 6638 — Scheduling Extensions](https://www.rfc-editor.org/rfc/rfc6638.html) — scheduling freebusy
- [RFC 7953 — Calendar Availability](https://www.rfc-editor.org/rfc/rfc7953.html) — VAVAILABILITY
- [Apple CalendarServer sharing spec](https://github.com/apple/ccs-calendarserver/blob/master/doc/Extensions/caldav-sharing.txt) — CS:share, CS:read/CS:read-write
- [Apple CalDAV proxy spec](https://github.com/apple/ccs-calendarserver/blob/master/doc/Extensions/caldav-proxy.txt) — delegation model
- [draft-pot-caldav-sharing](https://datatracker.ietf.org/doc/html/draft-pot-caldav-sharing-01) — expired IETF draft
- [SabreDAV sharing docs](https://sabre.io/dav/3.1/caldav-sharing/)
- [Nextcloud freebusy share request](https://github.com/nextcloud/server/issues/11214)
