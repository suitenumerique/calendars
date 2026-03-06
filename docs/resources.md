# Calendar Resources

This document describes the design and implementation plan for **calendar resources** in La Suite Calendars: meeting rooms, vehicles, projectors, and any other bookable assets that people can reserve alongside events.

## Table of Contents

- [Overview](#overview)
- [What Is a Calendar Resource?](#what-is-a-calendar-resource)
  - [Resource Scheduling Addresses](#resource-scheduling-addresses-not-real-emails)
  - [Email Safety](#email-safety)
- [CalDAV Standards and Interoperability](#caldav-standards-and-interoperability)
- [Data Model](#data-model)
- [Resource Lifecycle](#resource-lifecycle)
- [Booking Flow](#booking-flow)
- [Auto-Scheduling and Conflict Detection](#auto-scheduling-and-conflict-detection)
- [Free/Busy and Availability](#freebusy-and-availability)
- [Access Rights and Administration](#access-rights-and-administration)
- [Sharing and Delegation](#sharing-and-delegation)
- [Resource Discovery](#resource-discovery)
- [Interoperability with CalDAV Clients](#interoperability-with-caldav-clients)
- [Why a Custom Plugin?](#why-a-custom-plugin)
- [Implementation Plan](#implementation-plan)
  - [Phase 1: Resource Principals in SabreDAV](#phase-1-resource-principals-in-sabredav)
  - [Phase 2: Django Resource Management](#phase-2-django-resource-management)
  - [Phase 3: Auto-Scheduling Plugin](#phase-3-auto-scheduling-plugin)
  - [Phase 4: Frontend Resource UI](#phase-4-frontend-resource-ui)
  - [Phase 5: Advanced Features](#phase-5-advanced-features)
- [Database Schema Changes](#database-schema-changes)
- [API Design](#api-design)
- [SabreDAV Plugin Design](#sabredav-plugin-design)
- [Frontend Components](#frontend-components)
- [Migration and Deployment](#migration-and-deployment)

---

## Overview

Calendar resources allow organizations to manage shared physical assets (rooms, vehicles, equipment) through the calendar. Users book resources by adding them as attendees to events, just like inviting a person. The system handles availability checking, conflict prevention, and automatic accept/decline responses.

**Key principles:**

- Resources are modeled as CalDAV principals, following RFC 6638
- Any CalDAV client can book a resource by inviting its email address
- The server handles auto-scheduling (accept if free, decline if busy)
- Resource provisioning (create/delete) happens through Django; all other management through CalDAV
- Double-booking prevention is enforced server-side

---

## What Is a Calendar Resource?

A calendar resource is a bookable entity that is not a person. Resources fall into two categories defined by the iCalendar standard (RFC 5545):

| Type | CUTYPE | Examples |
|------|--------|----------|
| **Room** | `ROOM` | Conference rooms, meeting rooms, auditoriums, phone booths |
| **Resource** | `RESOURCE` | Projectors, vehicles, cameras, whiteboards, parking spots |

Each resource has:
- A **display name** (e.g., "Room 101 - Large Conference")
- A **scheduling address** (a `mailto:` URI used as a CalDAV identifier -- see below)
- A **calendar** that shows its bookings
- **Metadata** (capacity, location, description, equipment list)
- **Availability hours** (e.g., 8:00-20:00 on weekdays)
- An **auto-schedule policy** (auto-accept, require approval, etc.)
- One or more **administrators** who manage the resource

### Resource Scheduling Addresses (Not Real Emails)

In CalDAV, every principal (user or resource) is identified by a `mailto:` URI in the `calendar-user-address-set` property. This is how the scheduling protocol matches an `ATTENDEE` on an event to a principal on the server. **These addresses do not need to be real, routable email addresses.**

When SabreDAV receives a scheduling request for `mailto:c_a1b2c3d4@resource.calendar.example.com`, it looks up the `email` column in the `principals` table. If a matching principal is found locally, the iTIP message is delivered **internally** (inbox-to-inbox on the same server). See [Email Safety](#email-safety) for how outbound emails to resource addresses are prevented.

**Recommended convention**: `{opaque-id}@resource.calendar.{APP_DOMAIN}`

The address uses:
- An **opaque identifier** (UUID or short hash, prefixed with `c_`) rather than a human-readable slug, so renaming a resource doesn't change its address
- A **subdomain you control** (`resource.calendar.{APP_DOMAIN}`), which avoids collisions with real user emails and leaves the door open for future inbound email (e.g., resources acting as meeting organizers)

Examples (with `APP_DOMAIN=example.com`):
- `c_a1b2c3d4@resource.calendar.example.com`
- `c_f6g7h8i9@resource.calendar.example.com`

By default, no MX record is configured for this subdomain, so inbound email silently fails -- same practical effect as a non-routable address, but reversible if resources need to send/receive email in the future (e.g., room-initiated meetings with external attendees).

Org scoping is handled at the CalDAV/application level, not encoded in the email address.

The system identifies resource principals via the `calendar_user_type` column in the SabreDAV principals table, not by email pattern.

### Email Safety

Resource scheduling addresses are **not real mailboxes**. No email should ever be sent to or from them. However, the current invitation system (`HttpCallbackIMipPlugin` -> Django -> email) will attempt to email any attendee unless explicitly prevented. This must be handled at two levels:

#### Internal: Preventing Outbound Emails to Resources

In the current flow, when a user adds attendees to an event, `HttpCallbackIMipPlugin` POSTs to Django for each attendee, and Django sends an invitation email. Without intervention, Django would attempt to email the resource address.

**Fix 1 (SabreDAV)**: The `ResourceAutoSchedulePlugin` (priority 120) sets `$message->scheduleStatus` on the iTIP message before `HttpCallbackIMipPlugin` runs. The base `IMipPlugin` class skips messages that already have a status set, preventing the callback entirely.

**Fix 2 (Django, safety net)**: `CalendarInvitationService.send_invitation()` checks if the recipient is a resource address (by checking `calendar_user_type` of the principal or matching the `@resource.calendar.example.com` domain) and skips email sending.

Both should be implemented. The plugin is the primary gate; Django is the fallback.

#### External: What Happens When Outside Systems See the Address

When an event includes both a resource and external attendees, the ICS attachment in invitation emails lists all `ATTENDEE` properties, including the resource's `mailto:c_abc123@resource.calendar.example.com`. This is visible to external recipients. Here's why this is safe:

| Scenario | What happens | Risk |
|----------|-------------|------|
| External email client tries to send iTIP REPLY | REPLY goes to ORGANIZER only (the human), not to other attendees | None |
| External email client tries to contact all attendees | Email to `@resource.calendar.example.com` bounces (no MX record by default) | None |
| External CalDAV server tries to book the resource | iTIP REQUEST email to `@resource.calendar.example.com` bounces | None -- resources are only bookable through this server |
| CalDAV client connected to THIS server | Uses `SCHEDULE-AGENT=SERVER`; all scheduling goes through SabreDAV, no email | None |

By default no MX record exists for `resource.calendar.{APP_DOMAIN}`, so external email attempts bounce harmlessly. All legitimate resource interactions go through the CalDAV server. If resources need to send/receive email in the future (e.g., room-initiated meetings), an MX record can be added and inbound mail routed to the application.

---

## CalDAV Standards and Interoperability

### Relevant Standards

| Standard | Role |
|----------|------|
| **RFC 5545** (iCalendar) | Defines `CUTYPE` parameter (`ROOM`, `RESOURCE`) on `ATTENDEE` properties |
| **RFC 6638** (CalDAV Scheduling) | Defines `calendar-user-type` DAV property on principals; scheduling transport (inbox/outbox); `SCHEDULE-AGENT` parameter |
| **RFC 4791** (CalDAV) | Calendar collections, `free-busy-query` REPORT |
| **RFC 7953** (Calendar Availability) | `VAVAILABILITY` component for defining operating hours (future) |
| **draft-cal-resource-schema** | Resource metadata schema (capacity, booking window, manager, etc.) |
| **draft-pot-caldav-sharing** | Calendar sharing between principals |

### How Resources Work in CalDAV

In CalDAV, a resource is a **regular principal** with a special `calendar-user-type` property set to `ROOM` or `RESOURCE`. It has its own calendar home, schedule inbox, and schedule outbox, exactly like a user principal.

When a user creates an event with a resource as an attendee:

```
ATTENDEE;CUTYPE=ROOM;ROLE=NON-PARTICIPANT;PARTSTAT=NEEDS-ACTION;
 RSVP=TRUE:mailto:c_a1b2c3d4@resource.calendar.example.com
```

The CalDAV scheduling server (RFC 6638):
1. Detects the `ATTENDEE` on the event
2. Delivers an iTIP `REQUEST` to the resource's schedule inbox
3. A server-side agent checks the resource's calendar for conflicts
4. Sends an iTIP `REPLY` back with `PARTSTAT=ACCEPTED` or `PARTSTAT=DECLINED`

**Auto-scheduling is not standardized** -- it is a server implementation feature. RFC 6638 only defines the transport mechanism. This project implements auto-scheduling as a custom SabreDAV plugin (see [Why a Custom Plugin?](#why-a-custom-plugin) for rationale).

### What This Means for Interoperability

The critical insight: **resource booking does not require client-side support**. Any CalDAV client that can add an attendee by email address can book a resource. The server handles everything else. This means:

- Apple Calendar, Thunderbird, GNOME Calendar, and all CalDAV clients work out of the box
- Clients that support `CUTYPE` can display resources differently from people
- Clients that support `principal-property-search` can discover available resources
- The web frontend provides the richest experience (resource browser, availability view)

---

## Data Model

### Design Principle: CalDAV as Single Source of Truth

Resources are **entirely managed in CalDAV** -- metadata, calendar data, and access control. No Django model is needed.

- **Metadata** (name, capacity, location, equipment, etc.): DAV properties via PROPFIND/PROPPATCH
- **Calendar data** (bookings, free/busy): CalDAV calendar collections
- **Access control**: CalDAV sharing (`CS:share`) with privilege levels, the same mechanism already used for user calendar sharing
- **Scheduling config** (auto-schedule mode, booking policies): Custom DAV properties read by the SabreDAV plugin

Django's role is limited to:
- **Provisioning**: A REST endpoint to create/delete resource principals. CalDAV has no standard operation to create a principal, so this is the one justified exception to the "Django is a pass-through" rule. Django makes CalDAV requests to SabreDAV to set up the principal + calendar + initial properties.
- **Proxying**: The existing CalDAV proxy (`CalDAVProxyView`) forwards all CalDAV requests, including those for resource principals

This means **zero new Django models** for resources. The frontend manages resource permissions via `CalDavService.shareCalendar()` / `getCalendarSharees()`, exactly like it already does for user calendars.

### Resource as a CalDAV Principal

Each resource exists as a principal in SabreDAV with a single
dedicated calendar:

```
principals/resources/{resource-slug}
  -> calendar-home-set: /calendars/resources/{resource-slug}/
  -> schedule-inbox-URL: /calendars/resources/{resource-slug}/inbox/
  -> schedule-outbox-URL: /calendars/resources/{resource-slug}/outbox/
  -> calendar-user-type: ROOM | RESOURCE
  -> calendar-user-address-set: mailto:{opaque-id}@resource.calendar.example.com
```

The `mailto:` address is a CalDAV internal identifier, not a real
mailbox (see [Resource Scheduling Addresses](#resource-scheduling-addresses-not-real-emails)).

**A resource principal has exactly one calendar.** Although CalDAV
allows any principal to own multiple calendar collections, this
doesn't make sense for resources (a room has one schedule).
`MKCALENDAR` requests targeting a resource principal's calendar
home are rejected by a SabreDAV plugin (hooking
`beforeMethod:MKCALENDAR`). The single calendar is created during
provisioning and cannot be added to or removed independently.

### Resource Properties (CalDAV)

All resource metadata is stored as DAV properties on the resource's principal or default calendar, using standard properties where they exist and a project namespace (`{urn:lasuite:calendars}`) for the rest.

SabreDAV's `PropertyStorage` plugin persists custom properties in a `propertystorage` table automatically -- any property set via PROPPATCH is stored and returned via PROPFIND.

#### Standard Properties (on the principal or calendar collection)

| Property | Namespace | Where | Description |
|----------|-----------|-------|-------------|
| `displayname` | `{DAV:}` | Principal | Resource name |
| `calendar-user-type` | `{urn:ietf:params:xml:ns:caldav}` | Principal | `ROOM` or `RESOURCE` |
| `calendar-description` | `{urn:ietf:params:xml:ns:caldav}` | Calendar | Free-form description |
| `calendar-color` | `{http://apple.com/ns/ical/}` | Calendar | Hex color (e.g., `#4CAF50`) |
| `calendar-timezone` | `{urn:ietf:params:xml:ns:caldav}` | Calendar | VTIMEZONE component |

#### Semi-Standard Properties (Apple CalendarServer)

| Property | Namespace | Where | Description |
|----------|-----------|-------|-------------|
| `capacity` | `{http://calendarserver.org/ns/}` | Principal | Integer, number of seats/units |

#### Custom Properties (Project Namespace)

| Property | Namespace | Where | Type | Description |
|----------|-----------|-------|------|-------------|
| `location` | `{urn:lasuite:calendars}` | Principal | String | Building, floor, address |
| `equipment` | `{urn:lasuite:calendars}` | Principal | JSON array | `["Projector", "Whiteboard"]` |
| `tags` | `{urn:lasuite:calendars}` | Principal | JSON array | `["building-a", "video"]` |
| `auto-schedule-mode` | `{urn:lasuite:calendars}` | Principal | String | See auto-schedule modes below |
| `is-active` | `{urn:lasuite:calendars}` | Principal | Boolean | `true` / `false` |
| `restricted-access` | `{urn:lasuite:calendars}` | Principal | Boolean | Restrict booking to explicit access |
| `multiple-bookings` | `{urn:lasuite:calendars}` | Principal | Integer | Max concurrent bookings (1 = no overlap) |
| `max-booking-duration` | `{urn:lasuite:calendars}` | Principal | Duration | ISO 8601 (e.g., `PT4H`) |
| `booking-window-start` | `{urn:lasuite:calendars}` | Principal | Duration | How far ahead (e.g., `P90D`) |
| `booking-window-end` | `{urn:lasuite:calendars}` | Principal | Duration | Minimum notice (e.g., `PT1H`) |

#### Example: Reading Resource Properties

```xml
PROPFIND /principals/resources/room-101/
<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:"
    xmlns:C="urn:ietf:params:xml:ns:caldav"
    xmlns:A="http://apple.com/ns/ical/"
    xmlns:CS="http://calendarserver.org/ns/"
    xmlns:LS="urn:lasuite:calendars">
  <D:prop>
    <D:displayname/>
    <C:calendar-user-type/>
    <CS:capacity/>
    <LS:location/>
    <LS:equipment/>
    <LS:tags/>
    <LS:auto-schedule-mode/>
    <LS:is-active/>
  </D:prop>
</D:propfind>
```

#### Example: Setting Resource Properties

```xml
PROPPATCH /principals/resources/room-101/
<?xml version="1.0" encoding="utf-8"?>
<D:propertyupdate xmlns:D="DAV:"
    xmlns:CS="http://calendarserver.org/ns/"
    xmlns:LS="urn:lasuite:calendars">
  <D:set>
    <D:prop>
      <CS:capacity>20</CS:capacity>
      <LS:location>Building A, Floor 2</LS:location>
      <LS:equipment>["Projector", "Whiteboard", "Video conferencing"]</LS:equipment>
      <LS:tags>["video-conference", "whiteboard", "building-a"]</LS:tags>
      <LS:auto-schedule-mode>automatic</LS:auto-schedule-mode>
    </D:prop>
  </D:set>
</D:propertyupdate>
```

### Auto-Schedule Modes

Stored as the `{urn:lasuite:calendars}auto-schedule-mode` property on the resource principal. Inspired by Apple Calendar Server's proven model:

| Mode | Behavior |
|------|----------|
| `automatic` | Accept if free, decline if busy (default) |
| `accept-always` | Accept all invitations regardless of conflicts |
| `decline-always` | Decline all invitations (resource offline) |
| `manual` | Require a resource manager to accept/decline |

The `ResourceAutoSchedulePlugin` reads this property from SabreDAV's `propertystorage` table (same PostgreSQL instance) during scheduling -- no Django roundtrip needed.

### Resource Access (CalDAV Sharing)

Resource access uses the **same CalDAV sharing mechanism** (`CS:share`) already used for user calendar sharing. No Django model is needed.

The resource's calendar is shared with administrators/managers using the existing privilege levels:

| CalDAV Privilege | Role | Can Do |
|-----------------|------|--------|
| `read` | Viewer | See bookings, free/busy |
| `read-write` | Manager | See bookings, modify/cancel any booking |
| `admin` | Admin | Full control: edit properties, manage sharing, override bookings |

The frontend manages this via `CalDavService.shareCalendar()` and `getCalendarSharees()` -- the same code already used for sharing user calendars.

The resource creator is automatically the calendar owner (the principal itself owns the calendar collection). Additional admins are added via sharing.

### What About Search and Filtering?

Storing metadata in CalDAV raises the question: how do you filter resources by capacity, tags, or location?

For most deployments, the number of resources is small (tens to low hundreds). The frontend can:

1. **PROPFIND** on `principals/resources/` to fetch all resource principals with their properties in a single request
2. **Filter and sort client-side** in JavaScript (capacity >= 10, tags include "projector", etc.)

This is simple, avoids data duplication, and works well up to ~1000 resources. If a deployment needs SQL-level search across thousands of resources, a Django read-only index synced from CalDAV can be added later as an optimization -- but this is not needed for v1.

---

## Resource Lifecycle

### Creating a Resource

1. An **org admin** (`can_admin` entitlement) calls the Django
   REST API to create a resource (slug, name, type)
2. Django creates the SabreDAV principal via CalDAV requests,
   forwarding the admin's `X-Forwarded-Org` header so SabreDAV
   sets the resource's `org_id` to the admin's org:
   - Request to the resource's principal URL triggers
     `AutoCreatePrincipalBackend` (auto-creates the principal row
     with `calendar_user_type` and `org_id` set)
   - `MKCALENDAR` creates the default calendar collection
   - `PROPPATCH` sets initial properties (name, type)
3. The frontend sets additional metadata via PROPPATCH (capacity,
   location, equipment, etc.)
4. The resource is immediately available for booking

No Django model is created -- the CalDAV principal **is** the
resource.

### Updating a Resource

All metadata changes go through CalDAV `PROPPATCH` directly (from the frontend or via a Django proxy endpoint). There is no Django model to keep in sync.

- Display properties (name, color, description): PROPPATCH on the calendar collection
- Resource properties (capacity, equipment, location, tags): PROPPATCH on the principal
- Scheduling config (auto-schedule-mode, booking policies): PROPPATCH on the principal
- Deactivating a resource: set `{urn:lasuite:calendars}is-active` to `false`

### Deleting a Resource

1. Delete the CalDAV calendar collection (and its events)
2. Delete the SabreDAV principal
3. Sharing entries are automatically cleaned up with the calendar

Existing events in user calendars that reference the resource as
an attendee are **left as-is**. The resource's `mailto:` address
becomes an unresolvable address -- same as if an external attendee
disappeared. The resource will simply stop responding to scheduling
requests. This avoids the complexity of modifying events across
all user calendars.

---

## Booking Flow

### Standard Booking (Any CalDAV Client)

```
User                    CalDAV Server              Auto-Scheduler
  |                          |                          |
  |-- PUT event ------------>|                          |
  |   (ATTENDEE=c_...@resource.calendar.example.com)
  |                          |-- iTIP REQUEST --------->|
  |                          |                          |-- check free/busy
  |                          |                          |-- no conflict?
  |                          |<-- iTIP REPLY -----------|
  |                          |   (PARTSTAT=ACCEPTED)    |
  |<-- schedule-status ------|                          |
  |    (1.2 = delivered)     |                          |
```

### Web Frontend Booking

The web UI provides a richer experience:

1. User opens event creation modal
2. User clicks "Add Room" or "Add Resource"
3. A resource picker shows available resources with metadata
4. User selects a resource; frontend checks free/busy in real-time
5. Frontend adds the resource as an `ATTENDEE` with `CUTYPE=ROOM`
6. On save, the CalDAV flow triggers auto-scheduling
7. The event updates with the resource's `PARTSTAT` response

### Booking with Conflicts

When a resource is already booked:

1. User creates event with resource as attendee
2. Auto-scheduler detects conflict
3. Resource declines (`PARTSTAT=DECLINED`)
4. Organizer sees the declined status
5. Frontend shows a warning: "Room 101 is unavailable at this time"

### Recurring Event Booking

For recurring events, the auto-scheduler must check **every instance** within a reasonable window (e.g., 1 year) for conflicts. If any instance conflicts:

- **Option A (strict)**: Decline the entire series
- **Option B (lenient)**: Accept the series but decline specific instances via `EXDATE`

The recommended approach is **Option A** for simplicity, with the UI helping users find conflict-free times.

---

## Why a Custom Plugin?

No existing SabreDAV plugin or third-party package provides resource auto-scheduling. This was investigated thoroughly:

### SabreDAV Core

SabreDAV's `Schedule\Plugin` handles iTIP delivery (inbox/outbox) but has **no resource awareness**. The source code explicitly states: *"The server currently reports every principal to be of type INDIVIDUAL."* There is no CUTYPE differentiation, no auto-accept logic, and no conflict detection. The `principals` table schema only has `uri`, `email`, `displayname` -- no `calendar_user_type` column.

### Nextcloud

Nextcloud built resource scheduling on top of SabreDAV, but their implementation is **deeply coupled to the Nextcloud framework**:
- `apps/dav/lib/CalDAV/ResourceBooking/AbstractPrincipalBackend.php`, `ResourcePrincipalBackend.php`, `RoomPrincipalBackend.php` all depend on `\OCP\` interfaces (Nextcloud's DI container, app framework, database abstraction)
- Auto-accept logic lives in `CalDavBackend.php` which implements Nextcloud-specific `SchedulingSupport` interfaces
- Resource backends require implementing `\OCP\Calendar\Resource\IBackend` -- a Nextcloud-only interface
- None of this code is extractable as a standalone SabreDAV plugin

### SOGo

SOGo has resource auto-accept, but it is written in Objective-C with its own CalDAV stack -- not SabreDAV-based at all.

### Packagist / Open Source

No third-party SabreDAV resource scheduling package exists on Packagist or GitHub.

### What This Means

We need a custom `ResourceAutoSchedulePlugin` (~150-200 lines of PHP). The good news:
- The pattern is identical to this project's existing `HttpCallbackIMipPlugin`: listen for the `schedule` event, inspect the iTIP message, act on it
- SabreDAV's plugin architecture makes this straightforward -- hook into the `schedule` event at a priority after `Schedule\Plugin` delivers the message
- The auto-schedule logic (free/busy check + accept/decline) is the only new part
- The plugin reads resource configuration from the shared PostgreSQL database directly (same instance SabreDAV already uses)

---

## Auto-Scheduling and Conflict Detection

### How Auto-Scheduling Works

Auto-scheduling is implemented as a **custom SabreDAV plugin** that intercepts scheduling deliveries to resource principals. It runs after `Sabre\CalDAV\Schedule\Plugin` delivers the iTIP message. No existing SabreDAV plugin provides this functionality (see [Why a Custom Plugin?](#why-a-custom-plugin)).

```php
class ResourceAutoSchedulePlugin extends ServerPlugin
{
    // Hook into the 'schedule' event
    function schedule(ITip\Message $message)
    {
        // 1. Is the recipient a resource principal?
        // 2. What is the resource's auto_schedule_mode?
        // 3. For 'automatic' mode: check free/busy
        // 4. Set $message->scheduleStatus accordingly
        // 5. Update PARTSTAT in the delivered calendar object
    }
}
```

### Conflict Detection Algorithm

```
function hasConflict(resource, newEvent):
    // Get the resource's calendar
    calendar = resource.getDefaultCalendar()

    // For each instance of the new event (expand recurrence)
    for instance in expandInstances(newEvent, maxWindow=1year):
        if instance.transp == TRANSPARENT:
            continue  // transparent events don't block

        // Query existing events in this time range
        existing = calendar.getEvents(instance.start, instance.end)

        // Check against max concurrent bookings
        overlapping = countOverlapping(existing, instance)
        if overlapping >= resource.multiple_bookings:
            return true  // conflict

    return false  // no conflict
```

### Edge Cases

- **All-day events**: Treated as blocking the entire day
- **Tentative events**: Count as busy (configurable per resource)
- **Cancelled events**: Do not count as busy
- **Transparent events** (`TRANSP=TRANSPARENT`): Do not count as busy
- **Recurring with exceptions**: Must check each expanded instance

---

## Free/Busy and Availability

### Free/Busy Queries

Resources support standard CalDAV free/busy queries. Two methods:

**Method 1: `CALDAV:free-busy-query` REPORT** (RFC 4791)

```xml
REPORT /calendars/resources/room-101/default/
<?xml version="1.0" encoding="utf-8"?>
<C:free-busy-query xmlns:C="urn:ietf:params:xml:ns:caldav">
  <C:time-range start="20260305T000000Z" end="20260306T000000Z"/>
</C:free-busy-query>
```

Returns a `VFREEBUSY` component with busy intervals.

**Method 2: Schedule outbox POST** (RFC 6638)

The organizer POSTs a `VFREEBUSY` request to their outbox, specifying the resource as an attendee. The server returns the resource's free/busy data.

### Availability Hours (VAVAILABILITY) — Future

Resources could define operating hours using RFC 7953
`VAVAILABILITY` (e.g., Monday-Friday 8:00-20:00, booking outside
these hours auto-declined). However, SabreDAV does not support
RFC 7953 out of the box — the auto-schedule plugin would need to
implement `VAVAILABILITY` parsing. This is deferred to Phase 5.

### Frontend Availability View

The web frontend shows:
- A **day/week timeline** of the resource's bookings
- **Color-coded slots**: free (green), busy (red), tentative (yellow)
- A **multi-resource view** to compare several rooms side by side

---

## Access Rights and Administration

Resource access control uses **CalDAV sharing** (`CS:share`), the same mechanism already used for sharing user calendars. No Django model is needed.

### Privilege Levels

| CalDAV Privilege | Role | Capabilities |
|-----------------|------|--------------|
| *(no share)* | Any authenticated user | Discover resource, view free/busy, book by adding as attendee |
| `read` | Shared viewer | All of the above + see full booking details on the calendar |
| `read-write` | Manager | All of the above + modify/cancel any booking on the resource |
| `admin` | Administrator | All of the above + edit resource properties (PROPPATCH), manage sharing, override auto-schedule decisions, delete resource |

### How It Works

- The **resource principal** owns its calendar collection. This is the "owner" in CalDAV terms.
- **Admins** are added by sharing the resource's calendar with `admin` privilege via `CS:share` (same as `CalDavService.shareCalendar()`)
- **Managers** get `read-write` privilege
- **Viewers** get `read` privilege
- **Any authenticated user** can book the resource (add it as an attendee to their event) and query free/busy -- this does not require sharing. The CalDAV scheduling protocol handles this via the resource's schedule inbox.

This maps directly to how user calendar sharing already works in the frontend (`CalendarShareModal`, `CalDavService.shareCalendar()`, `getCalendarSharees()`).

### Restricted Resources

For resources that should not be bookable by everyone (executive rooms, specialized equipment), the `{urn:lasuite:calendars}restricted-access` property can be set to `true`. When set, the auto-schedule plugin only accepts invitations from users who have been explicitly shared on the resource's calendar.

### Organization Scoping and Permissions

See [docs/organizations.md](organizations.md) for the full org design. Key points for resources:

- **Resource discovery** is org-scoped: SabreDAV filters resource principals by the `org_id` column on the `principals` table, using the `X-Forwarded-Org` header set by Django.
- **Cross-org resource booking is not allowed**: the auto-schedule plugin rejects invitations from users outside the resource's org.
- **Resource creation** requires the `can_admin` entitlement (returned by the entitlements system alongside `can_access`).

---

## Sharing and Delegation

### Delegation to Resource Managers

When `auto-schedule-mode=manual`, incoming booking requests require approval:

1. User creates event with resource as attendee
2. Auto-scheduler detects `manual` mode
3. Resource stays in `PARTSTAT=NEEDS-ACTION`
4. Resource managers receive a notification
5. Manager approves or declines via:
   - The web UI (resource management panel)
   - Direct calendar interaction (change PARTSTAT on the resource's calendar)
6. iTIP REPLY sent back to the organizer

---

## Resource Discovery

### How Users Find Resources

In major calendar apps, users pick rooms from a list scoped to their organization. This works because those apps are tied to an organization directory (Workspace domain, Exchange GAL, etc.). In CalDAV, there are two discovery mechanisms:

### Discovery via CalDAV (`principal-property-search`)

RFC 3744 defines a `DAV:principal-property-search` REPORT that lets clients search for principals by property. For example, to find all rooms:

```xml
REPORT /principals/
<?xml version="1.0" encoding="utf-8"?>
<D:principal-property-search xmlns:D="DAV:"
    xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:property-search>
    <D:prop>
      <C:calendar-user-type/>
    </D:prop>
    <D:match>ROOM</D:match>
  </D:property-search>
  <D:prop>
    <D:displayname/>
    <C:calendar-user-address-set/>
  </D:prop>
</D:principal-property-search>
```

**Limitations**:
- Returns **all** matching principals on the server -- there is no built-in scoping by organization or tenant
- Only Apple Calendar uses this for resource discovery in practice
- Thunderbird and GNOME Calendar do not support resource discovery via CalDAV
- CalDAV properties are limited to basic fields (name, email, CUTYPE) -- no capacity, equipment, location metadata

**In a single-tenant deployment**, this works fine: all resources belong to the same organization, so returning all of them is correct.

**In a multi-tenant deployment**, SabreDAV filters results by the `org_id` on the `principals` table (see [Organization Scoping](#organization-scoping-and-permissions)).

### Discovery via CalDAV + Client-Side Filtering (Web Frontend)

The web frontend fetches all resource principals via a single
`PROPFIND` on `principals/resources/` (through the CalDAV proxy)
and filters/sorts **client-side** in JavaScript. This is the
**primary and richest** discovery method:

- Full metadata: capacity, equipment, location, tags
- Client-side filtering: by type, capacity, location, tags
- Real-time availability: via `free-busy-query` REPORT
- Org-scoped: SabreDAV filters by `org_id` before returning

No Django endpoint is needed for resource discovery. The frontend
does the same kind of PROPFIND it already does for calendars.

### Discovery via Email (All Clients)

Any CalDAV client can book a resource by typing its scheduling address in the attendee field, even without a discovery UI. This is the universal fallback that works everywhere.

## Interoperability with CalDAV Clients

| Client | Book by Email | See CUTYPE | Discover via CalDAV | Free/Busy |
|--------|---------------|------------|---------------------|-----------|
| Apple Calendar | Yes | Yes | Yes (`principal-property-search`) | Yes |
| Thunderbird | Yes | No (shows as person) | No | Yes |
| GNOME Calendar | Yes | Partial | No | Partial |
| Web Frontend | Yes | Yes | Yes (PROPFIND + client-side) | Yes |
| Any CalDAV client | Yes | Varies | Varies | Yes |

The key takeaway: **booking works universally** (any client can invite a resource by email). **Discovery** (browsing available rooms) is richest in the web frontend and limited in native CalDAV clients.

---

## Implementation Plan

### Phase 1: Resource Principals in SabreDAV

**Goal**: Resources exist as CalDAV principals and can receive scheduling messages.

**Changes**:

1. **Extend SabreDAV principals table**: Add `calendar_user_type` column
2. **Extend `AutoCreatePrincipalBackend`**: Map `{urn:ietf:params:xml:ns:caldav}calendar-user-type` to the new column; return it in `getPrincipalsByPrefix` and `getPrincipalByPath`
3. **Add resource principal prefix**: `principals/resources/` alongside existing `principals/` for users
4. **Verify scheduling delivery**: Ensure `Schedule\Plugin` delivers iTIP messages to resource inboxes

**Files to modify**:
- `docker/sabredav/pgsql.principals.sql` -- add column
- `docker/sabredav/src/AutoCreatePrincipalBackend.php` -- extend field map
- `docker/sabredav/server.php` -- add resource principal collection

### Phase 2: Django Provisioning API

**Goal**: REST endpoint to create/delete resource principals, gated by org-level permissions.

**Changes**:

1. **Resource provisioning endpoint**: Creates the SabreDAV principal + calendar via CalDAV requests (no direct DB writes). Checks the user's `can_admin` entitlement.
2. **Resource deletion endpoint**: Cleans up CalDAV principal + calendar. Same permission check.

No Django model is needed. Metadata is managed via CalDAV PROPPATCH. Access control uses CalDAV sharing (`CS:share`), the same way user calendars are shared. Org-level permission to create/delete resources comes from the `can_admin` entitlement.

**Files to create/modify**:
- `src/backend/core/api/viewsets.py` -- add resource provisioning viewset
- `src/backend/core/services/resource_service.py` -- provisioning logic (CalDAV calls)

### Phase 3: Auto-Scheduling Plugin

**Goal**: Resources automatically accept/decline based on availability.

No existing SabreDAV plugin provides this -- see [Why a Custom Plugin?](#why-a-custom-plugin). The plugin is ~150-200 lines of PHP, following the same pattern as the existing `HttpCallbackIMipPlugin`.

**Changes**:

1. **`ResourceAutoSchedulePlugin.php`**: SabreDAV plugin that hooks into the `schedule` event (same hook `HttpCallbackIMipPlugin` already uses)
2. **Conflict detection**: Query the resource's calendar for overlapping events
3. **Auto-schedule modes**: Read the `{urn:lasuite:calendars}auto-schedule-mode` property from SabreDAV's `propertystorage` table (same PostgreSQL instance, no Django roundtrip)
4. **iTIP REPLY generation**: Send `ACCEPTED` or `DECLINED` back to organizer
5. **Availability hours**: Not in v1 (see Phase 5)

**Files to create/modify**:
- `docker/sabredav/src/ResourceAutoSchedulePlugin.php` -- new plugin
- `docker/sabredav/server.php` -- register plugin

**Design choice**: The plugin reads the `auto_schedule_mode` from the database directly (same PostgreSQL instance SabreDAV already uses) rather than calling Django's API, to avoid circular HTTP dependencies during scheduling.

### Phase 4: Frontend Resource UI

**Goal**: Users can discover, browse, and book resources from the web interface.

**Components**:

1. **Resource directory**: Searchable/filterable list of all resources
2. **Resource detail panel**: Shows metadata, availability timeline, current bookings
3. **Resource picker in event modal**: Add room/resource when creating an event
4. **Availability checker**: Real-time free/busy display when selecting a resource
5. **Multi-resource timeline**: Side-by-side availability comparison
6. **Resource management panel**: For admins to create/edit/configure resources

**Files to create**:
- `src/frontend/apps/calendars/src/features/resources/` -- new feature module
  - `types.ts` -- TypeScript types for resource properties
  - `components/ResourceDirectory.tsx`
  - `components/ResourcePicker.tsx`
  - `components/ResourceDetail.tsx`
  - `components/ResourceTimeline.tsx`
  - `components/ResourceAdmin.tsx`
- `src/frontend/apps/calendars/src/services/dav/CalDavService.ts` -- extend with resource PROPFIND/PROPPATCH methods
- Updates to event modal for resource attendee support

The frontend reads/writes resource metadata via CalDAV (PROPFIND/PROPPATCH), the same way it already manages calendar properties. The Django REST API is only used for provisioning (create/delete).

### Phase 5: Advanced Features

**Goal**: Polish and power-user features.

1. **Approval workflow**: Notification system for `manual` mode resources
2. **Booking policies**: Max duration, booking window, recurring limits
3. **Resource groups**: Group rooms by building/floor for easier browsing
4. **Capacity warnings**: Warn when event attendee count exceeds room capacity
5. **Resource calendar overlay**: Show resource bookings in the main calendar view
6. **Reporting**: Usage statistics, popular times, underutilized resources
7. **VAVAILABILITY editor**: UI for configuring resource operating hours
8. **Bulk resource import**: CSV/JSON import for provisioning many resources

---

## Database Schema Changes

### SabreDAV: Principals Table

```sql
ALTER TABLE principals
    ADD COLUMN calendar_user_type VARCHAR(20) DEFAULT 'INDIVIDUAL';

-- Index for resource discovery queries
CREATE INDEX idx_principals_cutype
    ON principals (calendar_user_type)
    WHERE calendar_user_type IN ('ROOM', 'RESOURCE');
```

Resource metadata (capacity, location, equipment, etc.) is stored in SabreDAV's existing `propertystorage` table via PROPPATCH -- no additional SabreDAV schema changes needed.

### Django: No New Tables

No Django models are needed for resources. Access control uses CalDAV sharing (stored in SabreDAV's `calendarinstances` table). Resource metadata uses SabreDAV's `propertystorage` table. Both are managed through CalDAV protocol, not direct database access.

---

## API Design

Resource metadata is read/written via **CalDAV** (PROPFIND/PROPPATCH). The Django REST API only handles provisioning and deletion.

### Django REST API (Provisioning)

```
POST   /api/v1.0/resources/                         # Create resource (provision principal + calendar)
DELETE /api/v1.0/resources/{slug}/                   # Delete resource (cleanup principal + calendar)
```

Both `POST` and `DELETE` require the `can_admin` entitlement. Access control (sharing) is managed via CalDAV `CS:share` on the resource's calendar -- no Django access endpoints needed.

### Create Resource Request

```json
POST /api/v1.0/resources/
{
  "slug": "room-101",
  "name": "Room 101 - Large Conference",
  "resource_type": "ROOM"
}
```

Django checks the user's `can_admin` entitlement, provisions the CalDAV principal and calendar, then the frontend sets additional metadata via PROPPATCH.

### CalDAV API (Metadata and Discovery)

All resource metadata is managed via standard CalDAV protocol:

| Operation | Method | URL |
|-----------|--------|-----|
| List all resources | `PROPFIND` | `/api/v1.0/caldav/principals/resources/` |
| Get resource properties | `PROPFIND` | `/api/v1.0/caldav/principals/resources/{slug}/` |
| Update resource properties | `PROPPATCH` | `/api/v1.0/caldav/principals/resources/{slug}/` |
| Get resource calendar | `PROPFIND` | `/api/v1.0/caldav/calendars/resources/{slug}/default/` |
| Query free/busy | `REPORT` | `/api/v1.0/caldav/calendars/resources/{slug}/default/` |

The frontend fetches all resource principals with their properties in a single PROPFIND request and filters/sorts client-side. This is the same pattern used for fetching calendars today.

---

## SabreDAV Plugin Design

A custom plugin is required because SabreDAV has no built-in resource auto-scheduling, and no reusable third-party implementation exists (see [Why a Custom Plugin?](#why-a-custom-plugin)).

### ResourceAutoSchedulePlugin

```php
class ResourceAutoSchedulePlugin extends DAV\ServerPlugin
{
    function getPluginName() { return 'resource-auto-schedule'; }

    function initialize(DAV\Server $server)
    {
        $server->on('schedule', [$this, 'autoSchedule'], 120);
        // Priority 120: runs after Schedule\Plugin (110)
    }

    function autoSchedule(ITip\Message $message)
    {
        // Only handle messages TO resource principals
        if (!$this->isResourcePrincipal($message->recipient)) {
            return;
        }

        // Read auto-schedule-mode from propertystorage table
        $mode = $this->getAutoScheduleMode($message->recipient);

        switch ($mode) {
            case 'accept_always':
                $this->acceptInvitation($message);
                break;
            case 'decline_always':
                $this->declineInvitation($message);
                break;
            case 'automatic':
                if ($this->hasConflict($message)) {
                    $this->declineInvitation($message);
                } else {
                    $this->acceptInvitation($message);
                }
                break;
            case 'manual':
                // Do nothing; leave PARTSTAT=NEEDS-ACTION
                // Managers see pending requests on the resource calendar
                break;
        }
    }
}
```

### Integration with Existing Plugins

The plugin runs in this order:
1. `CalendarSanitizerPlugin` (priority 85) -- strips binaries, truncates
2. `AttendeeNormalizerPlugin` (priority 90) -- normalizes emails
3. `CalDAV\Schedule\Plugin` (priority 110) -- delivers iTIP messages
4. **`ResourceAutoSchedulePlugin`** (priority 120) -- auto-accept/decline
5. `HttpCallbackIMipPlugin` -- notifies Django (for email delivery)

---

## Frontend Components

### Data Flow

The frontend reads/writes resource metadata via CalDAV, just like it does for calendars:

```
CalDavService.fetchResourcePrincipals()   → PROPFIND /principals/resources/
CalDavService.getResourceProperties(slug)  → PROPFIND /principals/resources/{slug}/
CalDavService.updateResourceProperties()   → PROPPATCH /principals/resources/{slug}/
CalDavService.fetchResourceEvents()        → REPORT on resource calendar
CalDavService.queryResourceFreeBusy()      → free-busy-query REPORT
```

The Django REST API is only called for provisioning
(create/delete). Everything else goes through CalDAV.

### Resource Directory (`/resources`)

A browsable directory of all resources with:
- **Filter sidebar**: Type (room/resource), capacity range, tags, location, availability -- all filtering is client-side after a single PROPFIND
- **List/grid view**: Cards showing name, location, capacity, availability status
- **Search**: Real-time search across name, description, location
- **Quick book**: Click to start creating an event with the resource

### Resource Picker (Event Modal)

When creating/editing an event:
- "Add Room" / "Add Resource" button in the attendees section
- Opens a filtered dropdown/modal showing available resources
- Shows real-time availability for the selected event time
- Displays capacity and key metadata inline
- Selected resources appear in the attendees list with a room/resource icon

### Resource Timeline

A horizontal timeline showing:
- One row per resource
- Colored blocks for existing bookings
- Grey blocks for unavailable hours
- Ability to click an empty slot to book

### Resource Admin Panel

For resource administrators:
- Create/edit resource metadata (PROPPATCH to CalDAV)
- Configure auto-schedule mode and booking policies (PROPPATCH)
- Manage access via CalDAV sharing (`CS:share`) -- same UI as calendar sharing
- View booking history and usage stats
- Override booking decisions (accept/decline pending requests)

---

## Migration and Deployment

### Rolling Deployment Steps

1. **Database migration**: Add `calendar_user_type` to SabreDAV principals (no Django migration needed)
2. **Deploy SabreDAV**: Updated principal backend + auto-schedule plugin (no user impact -- new code paths only activate for resource principals)
3. **Deploy Django backend**: Resource provisioning + access endpoints (additive, no breaking changes)
4. **Deploy frontend**: Resource UI (feature-flagged if needed)

### Feature Flag

Consider a `RESOURCES_ENABLED` feature flag in settings to:
- Show/hide resource UI in the frontend
- Enable/disable resource API endpoints
- Allow gradual rollout

### Data Migration

If importing resources from an external system:
1. Call the Django provisioning endpoint for each resource (creates CalDAV principals)
2. PROPPATCH to set metadata properties on each resource principal
3. Import historical bookings as calendar events via ICS import
4. Verify free/busy accuracy after import
