# Entitlements System

The entitlements system provides a pluggable backend architecture for
checking whether a user is allowed to access the application. It
integrates with the DeployCenter API in production and uses a local
backend for development.

Unlike La Suite Messages, Calendars only checks `can_access` — there
is no admin permission sync.

## Architecture

```
┌─────────────────────────────────────────────┐
│       OIDC Authentication Backend           │
│  post_get_or_create_user() — warms cache    │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│          UserMeSerializer                   │
│    GET /users/me/ → { can_access: bool }    │
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
   `force_refresh=True` to warm the cache. Login always succeeds
   regardless of `can_access` value — access is gated at API level
   and in the frontend.
2. **User API** (`core/api/serializers.py`): `UserMeSerializer`
   exposes `can_access` as a field on `GET /users/me/`. Fail-open:
   returns `True` when entitlements are unavailable.
3. **Default calendar creation** (`core/signals.py`):
   `provision_default_calendar` checks entitlements before creating a
   calendar for a new user. Fail-closed: skips creation when
   entitlements are unavailable.
4. **CalDAV proxy** (`core/api/viewsets_caldav.py`): Blocks
   `MKCALENDAR` and `MKCOL` methods for non-entitled users.
   Other methods (PROPFIND, REPORT, GET, PUT, DELETE) are allowed
   so that users invited to shared calendars can still use them.
   Fail-closed: denies creation when entitlements are unavailable.
5. **Import events** (`core/api/viewsets.py`): Blocks
   `POST /calendars/import-events/` for non-entitled users.
   Fail-closed: denies import when entitlements are unavailable.
6. **Frontend** (`pages/index.tsx`, `pages/calendar.tsx`): Checks
   `user.can_access` and redirects to `/no-access` when `false`.
   Calendar creation uses MKCALENDAR via CalDAV proxy (no Django
   endpoint).

### Error handling

- **Login is fail-open**: if the entitlements service is unavailable,
  login succeeds and the cache warming is skipped.
- **User API is fail-open**: if the entitlements service is
  unavailable, `can_access` defaults to `True`.
- **Calendar creation is fail-closed**: if the entitlements service
  is unavailable, the default calendar is not created (avoids
  provisioning resources for users who may not be entitled).
- **CalDAV proxy MKCALENDAR/MKCOL is fail-closed**: if the
  entitlements service is unavailable, calendar creation via CalDAV
  is denied (returns 403).
- **Import events is fail-closed**: if the entitlements service is
  unavailable, ICS import is denied (returns 403).
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
| `oidc_claims` | No | OIDC claim names to forward as query params |

### Example production configuration

```bash
ENTITLEMENTS_BACKEND=core.entitlements.backends.deploycenter.DeployCenterEntitlementsBackend
ENTITLEMENTS_BACKEND_PARAMETERS='{"base_url":"https://deploycenter.example.com/api/v1.0/entitlements/","service_id":"calendar","api_key":"secret","timeout":10,"oidc_claims":["siret"]}'
ENTITLEMENTS_CACHE_TIMEOUT=300
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
        # Return: {"can_access": bool}
        # Raise EntitlementsUnavailableError on failure.
        pass
```

## DeployCenter API

The DeployCenter backend calls:

```
GET {base_url}?service_id=X&account_type=user&account_email=X
```

Headers: `X-Service-Auth: Bearer {api_key}`

Query parameters include any configured `oidc_claims` extracted from
the OIDC user_info response (e.g. `siret`).

Expected response: `{"entitlements": {"can_access": true}}`

## Access control flow

The entitlements check follows a two-step approach: the backend
exposes entitlements data, and the frontend gates access.

### On login

1. User authenticates via OIDC — login always succeeds
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
  (key: `entitlements:user:{user_sub}`, TTL:
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
| Calendar gating (signal) | `src/backend/core/signals.py` |
| CalDAV proxy gating | `src/backend/core/api/viewsets_caldav.py` |
| Import events gating | `src/backend/core/api/viewsets.py` |
| No-access page | `src/frontend/apps/calendars/src/pages/no-access.tsx` |
| Homepage gate | `src/frontend/apps/calendars/src/pages/index.tsx` |
| Calendar gate | `src/frontend/apps/calendars/src/pages/calendar.tsx` |
| Tests | `src/backend/core/tests/test_entitlements.py` |
