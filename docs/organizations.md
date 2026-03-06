# Organizations

How organizations and multi-tenancy work in La Suite Calendars:
scoping users, calendars, resources, and permissions by
organization.

## Table of Contents

- [Overview](#overview)
- [What Is an Organization in Calendars?](#what-is-an-organization-in-calendars)
- [Where Organization Context Comes From](#where-organization-context-comes-from)
  - [OIDC Claims](#oidc-claims)
  - [DeployCenter and Entitlements](#deploycenter-and-entitlements)
- [What Is Org-Scoped](#what-is-org-scoped)
- [Data Model](#data-model)
  - [Auto-Population on Login](#auto-population-on-login)
  - [Why a Local Model?](#why-a-local-model)
- [CalDAV and Multi-Tenancy](#caldav-and-multi-tenancy)
  - [The Core Problem](#the-core-problem)
  - [SabreDAV Principal Backend Filtering](#sabredav-principal-backend-filtering)
- [User Discovery and Sharing](#user-discovery-and-sharing)
- [Resource Scoping](#resource-scoping)
- [Entitlements Integration](#entitlements-integration)
- [Frontend Considerations](#frontend-considerations)
- [Implementation Plan](#implementation-plan)
  - [Phase 1: Org Context Propagation](#phase-1-org-context-propagation)
  - [Phase 2: User Discovery Scoping](#phase-2-user-discovery-scoping)
  - [Phase 3: CalDAV Scoping](#phase-3-caldav-scoping)
  - [Phase 4: Resource Scoping](#phase-4-resource-scoping)
- [Key Files](#key-files)

---

## Overview

La Suite Calendars scopes users, calendars, and resources by
organization. Every user belongs to exactly one org, determined by
their email domain (default) or a configurable OIDC claim. Orgs
are created automatically on first login.

The overarching constraint is that **CalDAV has no native concept of
organizations or tenants**. The protocol operates on principals,
calendars, and scheduling. Org scoping is layered on top via
SabreDAV backend filtering.

---

## What Is an Organization in Calendars?

An organization is a **boundary for user and resource visibility**.
Within an organization:

- Users discover and share calendars with other members
- Resources (meeting rooms, equipment) are visible and bookable
- Admins manage resources and org-level settings

Across organizations:

- Users cannot discover each other (unless explicitly shared with
  by email)
- Resources are invisible
- Scheduling still works via email (iTIP), just like scheduling
  with external users

An organization maps to a real-world entity: a company, a government
agency, a university department. It is identified by a **unique ID**
-- either a specific OIDC claim value (like a SIRET number in
France) or an **email domain** (the default).

---

## Where Organization Context Comes From

### OIDC Claims

The user's organization is identified at authentication time via an
OIDC claim. The identity provider (Keycloak) includes an org
identifier in the user info response:

```json
{
  "sub": "abc-123",
  "email": "alice@ministry.gouv.fr",
  "siret": "13002526500013"
}
```

The claim used to identify the org (e.g. `siret`) is configured via
`OIDC_USERINFO_ORGANIZATION_CLAIM`. When no claim is configured, the email
domain is used as the org identifier.

The claim names and their meaning depend on the Keycloak
configuration and the identity federation in use (AgentConnect for
French public sector, ProConnect, etc.).

### DeployCenter and Entitlements

The [entitlements system](entitlements.md) already forwards
OIDC claims to DeployCenter. The `oidc_claims` parameter in the
DeployCenter backend config specifies which claims to include:

```json
{
  "oidc_claims": ["siret"]
}
```

DeployCenter uses the `siret` claim to determine which organization
the user belongs to and whether they have access to the Calendars
service. It also knows the **organization name** (e.g. "Ministere
X") and returns it in the entitlements response. This means the
entitlements system is the **source of truth for org names** --
Calendars does not need a separate OIDC claim for the org name.

---

## What Is Org-Scoped

| Feature | Behavior |
|---------|----------|
| **User discovery** (search when sharing) | Same-org users only |
| **Calendar sharing suggestions** | Same-org users; cross-org by typing full email |
| **Resource discovery** | Same-org resources only |
| **Resource creation** | Org admins only (`can_admin` entitlement) |
| **Resource booking** | Same-org users only |
| **Free/busy lookup** | Same-org principals |

Things that are **not** org-scoped:

- **Event scheduling via email**: iTIP works across orgs (same as
  external users)
- **Calendar sharing by email**: A user can share a calendar with
  anyone by typing their email address
- **CalDAV protocol operations**: PUT, GET, PROPFIND on a user's
  own calendars
- **Subscription tokens**: Public iCal URLs

---

## Data Model

A lightweight `Organization` model stores just enough to scope
data. It is auto-populated on login from the OIDC claim (or email
domain) and the entitlements response.

```python
class Organization(BaseModel):
    """Organization model, populated from OIDC claims and entitlements."""
    name = models.CharField(max_length=200, blank=True)
    external_id = models.CharField(
        max_length=128, unique=True, db_index=True
    )

    class Meta:
        db_table = "calendars_organization"
```

A FK on User links each user to their org:

```python
class User(AbstractBaseUser, ...):
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="members"
    )
```

### Auto-Population on Login

On OIDC login, `post_get_or_create_user()` resolves the org. The
org identifier (`external_id`) comes from the OIDC claim or
email domain. The org **name** comes from the entitlements response.

```python
# 1. Determine the org identifier
claim_key = settings.OIDC_USERINFO_ORGANIZATION_CLAIM  # e.g. "siret"
if claim_key:
    reg_id = user_info.get(claim_key)
else:
    # Default: derive org from email domain
    reg_id = user.email.split("@")[-1] if user.email and "@" in user.email else None

# 2. Get org name from entitlements (looked up from DeployCenter)
org_name = entitlements.get("organization_name", "")

# 3. Create or update the org
if reg_id:
    org, created = Organization.objects.get_or_create(
        external_id=reg_id,
        defaults={"name": org_name}
    )
    if not created and org_name and org.name != org_name:
        org.name = org_name
        org.save(update_fields=["name"])
    if user.organization_id != org.id:
        user.organization = org
        user.save(update_fields=["organization"])
```

By default, the org is derived from the **user's email domain**
(e.g. `alice@ministry.gouv.fr` → org `ministry.gouv.fr`). Orgs
are always created automatically on first login.

`OIDC_USERINFO_ORGANIZATION_CLAIM` can override this with a specific OIDC
claim (e.g. `"siret"` for French public sector, `"organization_id"`
for other identity providers).

The org name is kept in sync: each login updates it from the
entitlements response if it has changed. If entitlements are
unavailable on login (fail-open), the org is still created from
the OIDC claim or email domain, but the name is left empty until
a subsequent login succeeds.

### Why a Local Model?

- **Efficient queries**: `User.objects.filter(organization=org)`
  for user search scoping, instead of JSONField queries on claims
- **Org-level settings**: Place to attach resource creation policy,
  default timezone, branding, etc.
- **SabreDAV integration**: The org's Django UUID is forwarded to
  SabreDAV as `X-CalDAV-Organization` for principal scoping
- **Claim-agnostic**: The claim name is a setting, not hardcoded

---

## CalDAV and Multi-Tenancy

### The Core Problem

CalDAV principals live in a flat namespace: `principals/{username}`.
When a frontend does a `PROPFIND` on `principals/` or a
`principal-property-search`, SabreDAV returns **all** principals.
There is no built-in way to scope results by organization.

The same applies to scheduling: `calendar-free-busy-set` returns
free/busy for any principal the server knows about.

A design principle is that **Django should not inspect or filter
CalDAV traffic**. The `CalDAVProxyView` is a pass-through proxy --
it sets authentication headers and forwards requests, but never
parses CalDAV XML. Org scoping must happen either in SabreDAV
itself or in the frontend.

### SabreDAV Principal Backend Filtering

Org scoping is enforced server-side in SabreDAV by filtering
principal queries by `org_id`. Django never inspects CalDAV
traffic -- it only sets the `X-CalDAV-Organization` header.

```php
class OrgAwarePrincipalBackend extends AutoCreatePrincipalBackend
{
    public function searchPrincipals($prefixPath, array $searchProperties, $test = 'allof')
    {
        $orgId = $this->server->httpRequest->getHeader('X-CalDAV-Organization');
        // Add WHERE org_id = $orgId to the query
        return parent::searchPrincipals(...) + org filter;
    }
}
```

**Implementation:**
1. Add `org_id` column to `principals` table
2. Set it when auto-creating principals (from `X-CalDAV-Organization`)
3. Filter discovery and listing methods by org (see below)
4. `CalDAVProxyView` always sets `X-CalDAV-Organization` from the
   authenticated user's org

**Which backend methods are org-filtered:**

| Method | Filtered? | Why |
|--------|-----------|-----|
| `searchPrincipals()` | Yes | Used for user/resource discovery |
| `getPrincipalsByPrefix()` | Yes | Used for listing principals |
| `getPrincipalByPath()` | **No** | Used for sharing and scheduling with a specific principal — must work cross-org |
| Schedule outbox free/busy | Yes | Aggregates all calendars for a principal — scoped to same-org |
| `free-busy-query` on a specific calendar | **No** | If a user has access to a shared calendar, they can query its free/busy regardless of org |

This keeps principal paths stable (`principals/{username}` -- no
org baked into the URI), enforces scoping at the CalDAV level for
both web and external clients (Apple Calendar, Thunderbird), and
allows cross-org sharing to work when explicitly granted.

---

## User Discovery and Sharing

When a user types an email to share a calendar, the frontend
currently searches all users. With orgs:

### Same-Org Discovery

The user search endpoint (`GET /api/v1.0/users/?q=alice`) should
return only users in the same organization by default. This is a
Django-side filter:

```python
# In UserViewSet.get_queryset():
queryset = queryset.filter(organization=request.user.organization)
```

### Cross-Org Sharing

Typing a full email address that doesn't match any same-org user
should still work. The frontend sends the sharing request to CalDAV
with the email address. SabreDAV resolves the recipient via
`getPrincipalByPath()`, which is **not org-filtered** -- so
cross-org sharing works. If the recipient is external (not on this
server), an iTIP email is sent.

Once shared, the recipient can see that calendar's events and
query its free/busy (via `free-busy-query` on the specific
calendar collection), regardless of org. They still cannot
discover the sharer's other calendars or query their aggregate
free/busy via the scheduling outbox.

The UI should make this distinction clear:
- Autocomplete results: same-org users
- Manual email entry: "This user is outside your organization"

### CalDAV User Search

The CalDAV `principal-property-search` REPORT is how external
CalDAV clients discover users. SabreDAV only returns principals
from the user's org.

---

## Resource Scoping

Resource discovery and booking scoping follows the same pattern as
user scoping. See [docs/resources.md](resources.md) for the full
resource design.

Key points for org scoping of resources:

1. **Resource principals** get an org association (same `org_id`
   column on the `principals` table as user principals)
2. **Resource discovery** is scoped to the user's org
3. **Resource creation** requires an org-admin permission
4. **Resource email addresses** follow the convention
   `{opaque-id}@resource.calendar.{APP_DOMAIN}` -- the org is
   **not** encoded in the email address (see resources.md for
   rationale)
5. **No cross-org resource booking** -- the auto-schedule plugin
   rejects invitations from users outside the resource's org

The resource creation permission gate checks the user's
`can_admin` entitlement, returned by the entitlements system
alongside `can_access`.

---

## Entitlements Integration

The [entitlements system](entitlements.md) controls whether a user
can access Calendars at all. Organizations add a layer on top:

```
User authenticates
  → Entitlements check: can_access? (DeployCenter, per-user)
  → Org resolution: which org? (OIDC claim or email domain)
  → Org name: from entitlements response
  → Scoping: show only org's users/resources
```

The entitlements backend already receives OIDC claims (including
`siret`). DeployCenter resolves the organization and returns the
org name alongside the access decision:

```json
{
  "can_access": true,
  "can_admin": false,
  "organization_name": "Ministere X"
}
```

On login, `post_get_or_create_user()` uses the entitlements
response to populate the organization name. The org's
`external_id` is determined locally (from the OIDC claim or
email domain), but the **display name comes from DeployCenter**.
This avoids requiring a separate OIDC claim for the org name and
keeps DeployCenter as the single source of truth for org metadata.

---

## Frontend Considerations

### Org-Aware UI Elements

- **User search/autocomplete:** Filter results to same-org users by
  default; show a "search all users" or "invite by email" option for
  cross-org
- **Resource picker:** Only show resources from the user's org
- **Calendar list:** No change (users only see calendars they own or
  are shared on)
- **No-access page:** Already exists (from entitlements). Could show
  org-specific messaging
- **Org switcher:** Not needed (a user belongs to exactly one org)

### Org Context in Frontend State

The frontend needs to know the user's org ID to:
- Scope user search API calls
- Scope resource PROPFIND requests
- Display org name in the UI

This can come from the `GET /users/me/` response:

```json
{
  "id": "user-uuid",
  "email": "alice@ministry.gouv.fr",
  "organization": {
    "id": "org-uuid",
    "name": "Ministere X"
  }
}
```

---

## Implementation Plan

### Phase 1: Org Context Propagation

**Goal:** Every request knows the user's org.

1. Add `OIDC_USERINFO_ORGANIZATION_CLAIM` setting (default: `""`, uses email
   domain)
2. Add `Organization` model (id, name, external_id)
3. Add `organization` FK on `User` (non-nullable -- every user has
   an org)
4. In `post_get_or_create_user()`, resolve org from email domain or
   OIDC claim and set `user.organization`
5. Expose `organization` in `GET /users/me/` response
6. Frontend stores org context from `/users/me/`

### Phase 2: User Discovery Scoping

**Goal:** User search returns same-org users by default.

1. Scope `UserViewSet` queryset by org when org is set
2. Frontend user search autocomplete uses scoped endpoint
3. Cross-org sharing still works via explicit email entry
4. Add `X-CalDAV-Organization` header to `CalDAVProxyView` requests

### Phase 3: CalDAV Scoping

**Goal:** CalDAV operations are org-scoped.

1. Add `org_id` column to SabreDAV `principals` table
2. Set `org_id` when auto-creating principals (from
   `X-CalDAV-Organization`)
3. Extend `AutoCreatePrincipalBackend` to filter
   `searchPrincipals()`, `getPrincipalsByPrefix()`, and free/busy
   by org
4. Test with external CalDAV clients (Apple Calendar, Thunderbird)

### Phase 4: Resource Scoping

**Goal:** Resources are org-scoped (depends on resources being
implemented -- see [docs/resources.md](resources.md)).

1. Resource creation endpoint requires org-admin permission
2. Resource principals get org association
3. Resource discovery is scoped by org
4. Resource booking respects org boundaries

---

## Key Files

| Area | Path |
|------|------|
| User model (claims) | `src/backend/core/models.py` |
| OIDC auth backend | `src/backend/core/authentication/backends.py` |
| OIDC settings | `src/backend/calendars/settings.py` |
| CalDAV proxy | `src/backend/core/api/viewsets_caldav.py` |
| Entitlements system | `src/backend/core/entitlements/` |
| User serializer | `src/backend/core/api/serializers.py` |
| SabreDAV principal backend | `src/caldav/src/AutoCreatePrincipalBackend.php` |
| SabreDAV server config | `src/caldav/server.php` |
| Resource scoping details | `docs/resources.md` |
| Entitlements details | `docs/entitlements.md` |

---

## Design Decisions

1. **A user belongs to exactly one org**, determined by the OIDC
   claim at login.
2. **Cross-org calendar sharing is allowed** -- a user can share by
   email with anyone. Autocomplete only shows same-org users;
   cross-org sharing requires typing the full email.
3. **Cross-org resource booking is not allowed** -- the
   auto-schedule plugin rejects invitations from users outside the
   resource's org.
4. **Org scoping is enforced in SabreDAV**, not in Django. Django
   only sets `X-CalDAV-Organization` on proxied requests.
5. **Org is derived from email domain by default**. A specific OIDC
   claim can be configured via `OIDC_USERINFO_ORGANIZATION_CLAIM` (e.g.
   `siret` for French public sector).
