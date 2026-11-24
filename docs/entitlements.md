# Entitlements System

The entitlements system provides a pluggable backend architecture for
checking whether a user is allowed to access the application. It
integrates with the DeployCenter API in production and uses a local
backend for development.

Calendars checks two entitlements:
- `can_access`: whether the user can use the app at all
- `can_admin`: whether the user is an admin of their organization
  (e.g. can create/delete resources)

## Architecture

```
┌─────────────────────────────────────────────┐
│       OIDC Authentication Backend           │
│  post_get_or_create_user() — warms cache    │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│          UserMeSerializer                   │
│  GET /users/me/ → { can_access, can_admin } │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│            Service Layer                    │
│       get_user_entitlements()               │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│       Backend Factory (singleton)           │
│       get_entitlements_backend()            │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴───────┐
       │               │
┌──────▼─────┐  ┌──────▼───────────────┐
│   Local    │  │    DeployCenter      │
│  Backend   │  │      Backend         │
│ (dev/test) │  │ (production, cached) │
└────────────┘  └──────────────────────┘
```

### Components

- **Service layer** (`core/entitlements/__init__.py`): Public
  `get_user_entitlements()` function and
  `EntitlementsUnavailableError` exception.
- **Backend factory** (`core/entitlements/factory.py`):
  `@functools.cache` singleton that imports and instantiates the
  configured backend class.
- **Abstract base** (`core/entitlements/backends/base.py`): Defines
  the `EntitlementsBackend` interface.
- **Local backend** (`core/entitlements/backends/local.py`): Always
  grants access. Used for local development.
- **DeployCenter backend**
  (`core/entitlements/backends/deploycenter.py`): Calls the
  DeployCenter API with Django cache and stale fallback.

### Integration points

1. **OIDC login** (`core/authentication/backends.py`):
   `post_get_or_create_user()` calls `get_user_entitlements()` with
   `force_refresh=True` to warm the cache. A denial or an unavailable
   entitlements service does not refuse a valid login. The API and the
   frontend gate the access.
2. **User API** (`core/api/serializers.py`): `UserMeSerializer`
   exposes `can_access` as a field on `GET /users/me/`. Fail-closed:
   returns `False` when entitlements are unavailable.
3. **CalDAV proxy** (`core/api/viewsets_caldav.py`): Blocks
   calendar management for non-entitled users: `MKCALENDAR`,
   `MKCOL`, and `DELETE` or `MOVE` on a calendar collection.
   Event-level methods (PROPFIND, REPORT, GET, PUT, and DELETE or
   MOVE on an `.ics` object) stay allowed. Users invited to shared
   calendars can still use them. A user who loses the entitlement
   can still remove events. Fail-closed: denies calendar management
   when entitlements are unavailable.

   Known limitation: a sharee leaves a shared calendar with a `DELETE`
   on their own calendar instance. This is a collection `DELETE`, so a
   non-entitled sharee cannot leave a shared calendar.
   The frontend sends non-entitled users to `/no-access`, so this
   mainly affects external CalDAV clients.
4. **Import events** (`core/api/viewsets.py`): Blocks
   `POST /calendars/import-events/` for non-entitled users.
   Fail-closed: denies import when entitlements are unavailable.
5. **Frontend** (`routes/index.tsx`, `features/auth/Auth.tsx`): Checks
   `user.can_access` and redirects to `/no-access` when `false`.
   Calendar creation uses MKCALENDAR via CalDAV proxy (no Django
   endpoint).

### Error handling

- **Login is fail-open**: if the entitlements service is unavailable,
  login succeeds and the cache warming is skipped.
- **User API is fail-closed**: if the entitlements service is
  unavailable, `can_access` defaults to `False`.
- **CalDAV calendar management is fail-closed**: if the
  entitlements service is unavailable, the CalDAV proxy denies
  `MKCALENDAR`, `MKCOL`, and collection `DELETE` or `MOVE`
  (returns 403).
- **Import events is fail-closed**: if the entitlements service is
  unavailable, ICS import is denied (returns 403).
- **Resource provisioning is fail-closed**: if the entitlements
  service is unavailable, resource creation/deletion is denied
  (returns 403). The `can_admin` check follows the same pattern
  as `can_access` fail-closed checks.
- The DeployCenter backend falls back to stale cached data when the
  API is unavailable.
- `EntitlementsUnavailableError` is only raised when the API fails
  **and** no cache exists.

## Configuration

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `ENTITLEMENTS_BACKEND` | `core.entitlements.backends.local.LocalEntitlementsBackend` | Python import path of the backend class |
| `ENTITLEMENTS_BACKEND_PARAMETERS` | `{}` | JSON object passed to the backend constructor |
| `ENTITLEMENTS_CACHE_TIMEOUT` | `300` | Cache TTL in seconds |

### DeployCenter backend parameters

When using
`core.entitlements.backends.deploycenter.DeployCenterEntitlementsBackend`,
provide these in `ENTITLEMENTS_BACKEND_PARAMETERS`:

```json
{
  "base_url": "https://deploycenter.example.com/api/v1.0/entitlements/",
  "service_id": "calendar",
  "api_key": "your-api-key",
  "timeout": 10,
  "oidc_claims": ["siret"]
}
```

| Parameter | Required | Description |
|---|---|---|
| `base_url` | Yes | Full URL of the DeployCenter entitlements endpoint |
| `service_id` | Yes | Service identifier in DeployCenter |
| `api_key` | Yes | API key for `X-Service-Auth: Bearer` header |
| `timeout` | No | HTTP timeout in seconds (default: 10) |
| `oidc_claims` | Yes | OIDC claim names to forward as query params. Must contain `siret` |

### Example production configuration

```bash
ENTITLEMENTS_BACKEND=core.entitlements.backends.deploycenter.DeployCenterEntitlementsBackend
ENTITLEMENTS_BACKEND_PARAMETERS='{"base_url":"https://deploycenter.example.com/api/v1.0/entitlements/","service_id":"calendar","api_key":"secret","timeout":10,"oidc_claims":["siret"]}'
ENTITLEMENTS_CACHE_TIMEOUT=300
OIDC_USERINFO_ORGANIZATION_CLAIM=siret
```

## Backend interface

Custom backends must extend `EntitlementsBackend` and implement:

```python
class MyBackend(EntitlementsBackend):
    def __init__(self, **kwargs):
        # Receives ENTITLEMENTS_BACKEND_PARAMETERS as kwargs
        pass

    def get_user_entitlements(
        self, user_sub, user_email, user_info=None, force_refresh=False
    ):
        # Return: {"can_access": bool, "can_admin": bool, ...}
        # Raise EntitlementsUnavailableError on failure.
        pass
```

## DeployCenter API

The DeployCenter backend calls:

```
GET {base_url}?service_id=X&account_type=user&account_email=X
```

Headers: `X-Service-Auth: Bearer {api_key}`

Query parameters include the configured `oidc_claims` (e.g. `siret`).
DeployCenter requires `siret` on each request. Set `oidc_claims` to
`["siret"]` and `OIDC_USERINFO_ORGANIZATION_CLAIM` to `siret`: after
login, the backend sends the `external_id` of the user's organization.

Expected response:
`{"entitlements": {"can_access": true, "is_admin": false}}`

DeployCenter gives `is_admin` only when the organization has a
Calendars subscription. Access can come from the Messages subscription
alone.

## Access control flow

The entitlements check follows a two-step approach: the backend
exposes entitlements data, and the frontend gates access.

### On login

1. User authenticates via OIDC. A denial or an unavailable
   entitlements service does not refuse a valid login.
2. `post_get_or_create_user` calls `get_user_entitlements()` with
   `force_refresh=True` to warm the cache
3. If entitlements are unavailable, a warning is logged but login
   proceeds

### On page load

1. Frontend calls `GET /users/me/` which includes `can_access`
2. If `can_access` is `false`, the frontend redirects to `/no-access`
3. The user remains authenticated — they see the header, logo, and
   their profile, but cannot use the app
4. The `/no-access` page offers a logout button and a message to
   contact support

This approach ensures users always have a session (important for
shared calendars and other interactions) while still gating access to
the main application.

### Caching behavior

- The DeployCenter backend caches results in Django's cache framework
  (key: `entitlements:user:{user_sub}:{claims}`, TTL:
  `ENTITLEMENTS_CACHE_TIMEOUT`).
- On login, `force_refresh=True` bypasses the cache for fresh data.
- If the API fails during a forced refresh, stale cached data is
  returned as fallback.
- Subsequent `GET /users/me/` calls use the cached value (no
  `force_refresh`).

## Frontend

Users denied access see `/no-access` — a page using the main layout
(header with logo and user profile visible) with:

- A message explaining the app is not available for their account
- A suggestion to contact support
- A logout button

The user is fully authenticated and can see their profile in the
header, but cannot access calendars or events.

## Key files

| Area | Path |
|------|------|
| Service layer | `src/backend/core/entitlements/__init__.py` |
| Backend factory | `src/backend/core/entitlements/factory.py` |
| Abstract base | `src/backend/core/entitlements/backends/base.py` |
| Local backend | `src/backend/core/entitlements/backends/local.py` |
| DeployCenter backend | `src/backend/core/entitlements/backends/deploycenter.py` |
| Auth integration | `src/backend/core/authentication/backends.py` |
| User API serializer | `src/backend/core/api/serializers.py` |
| CalDAV proxy gating | `src/backend/core/api/viewsets_caldav.py` |
| Import events gating | `src/backend/core/api/viewsets.py` |
| No-access page | `src/frontend/src/routes/no-access.tsx` |
| Homepage gate | `src/frontend/src/routes/index.tsx` |
| Auth gate | `src/frontend/src/features/auth/Auth.tsx` |
| Tests | `src/backend/core/tests/test_entitlements.py` |
