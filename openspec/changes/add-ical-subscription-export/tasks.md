# Tasks: iCal Subscription Export

## 1. Backend - Data Model

- [x] 1.1 Create `CalendarSubscriptionToken` model in `core/models.py`
  - ForeignKey to User (owner, on_delete=CASCADE)
  - `caldav_path` field (CharField, max_length=512) - stores CalDAV path directly
  - `calendar_name` field (CharField, max_length=255, optional) - for display
  - `token` field (UUID, unique, indexed, default=uuid4)
  - `is_active` boolean (default=True)
  - `last_accessed_at` DateTimeField (nullable)
  - UniqueConstraint on (owner, caldav_path)
- [x] 1.2 Create and run database migration
- [x] 1.3 Add model to Django admin for debugging

## 2. SabreDAV - Enable ICSExportPlugin

- [x] 2.1 Add `ICSExportPlugin` to `server.php`:
  ```php
  $server->addPlugin(new CalDAV\ICSExportPlugin());
  ```
- [x] 2.2 Test that `?export` works via existing CalDAV proxy

## 3. Backend - Public iCal Endpoint

- [x] 3.1 Create `ICalExportView` in `core/api/viewsets_ical.py`
  - No authentication required (public endpoint)
  - Extract token from URL path
  - Lookup `CalendarSubscriptionToken` by token
  - Return 404 if token invalid/inactive
  - Update `last_accessed_at` on access
  - Proxy request to SabreDAV using `token.caldav_path` and `token.owner.email`
  - Return ICS response with `Content-Type: text/calendar`
  - Set security headers (Cache-Control, Referrer-Policy)
- [x] 3.2 Add URL route: `path('ical/<uuid:token>.ics', ...)`
- [x] 3.3 Write tests for public endpoint (valid token, invalid token, inactive)

## 4. Backend - Standalone Token Management API

- [x] 4.1 Create serializers in `core/api/serializers.py`
  - `CalendarSubscriptionTokenSerializer` - fields: token, url, caldav_path, calendar_name, etc.
  - `CalendarSubscriptionTokenCreateSerializer` - for POST body validation
- [x] 4.2 Create standalone `SubscriptionTokenViewSet` in `core/api/viewsets.py`:
  - `POST /subscription-tokens/` - create token with { caldav_path, calendar_name }
  - `GET /subscription-tokens/by-path/?caldav_path=...` - get existing token
  - `DELETE /subscription-tokens/by-path/?caldav_path=...` - revoke token
  - Permission verification: user's email must be in caldav_path
- [x] 4.3 Register viewset in `core/urls.py`
- [x] 4.4 Write API tests for token management (create, get, delete, permissions)

## 5. Frontend - API Integration

- [x] 5.1 Add API functions in `features/calendar/api.ts`:
  - `getSubscriptionToken(caldavPath)` - GET by-path
  - `createSubscriptionToken({ caldavPath, calendarName })` - POST
  - `deleteSubscriptionToken(caldavPath)` - DELETE by-path
- [x] 5.2 Update React Query hooks in `hooks/useCalendars.ts`
  - Use caldavPath instead of calendarId

## 6. Frontend - UI Components

- [x] 6.1 Update `SubscriptionUrlModal` component
  - Accept `caldavPath` prop instead of `calendarId`
  - Extract caldavPath from calendar URL in parent component
  - Display the subscription URL in a copyable field
  - "Copy to clipboard" button with success feedback
  - Warning text about URL being private
  - "Regenerate URL" button with confirmation dialog
  - Only show error alert for real errors (not for expected 404)
- [x] 6.2 Update `CalendarList.tsx`
  - Extract CalDAV path from calendar URL
  - Pass caldavPath to SubscriptionUrlModal
- [x] 6.3 Add translations (i18n) for new UI strings

## 7. Cleanup

- [x] 7.1 Remove old `subscription_token` action from CalendarViewSet
- [x] 7.2 Remove `sync-from-caldav` endpoint (no longer needed)
- [x] 7.3 Remove `syncFromCaldav` from frontend API

## 8. Testing & Validation

- [x] 8.1 Manual test: add URL to Apple Calendar
- [ ] 8.2 Manual test: add URL to Google Calendar
- [x] 8.3 Verify token regeneration invalidates old URL
- [ ] 8.4 E2E test for subscription workflow (optional)

## Dependencies

```
1 (Django model)
    ↓
2 (ICSExportPlugin) ──────┐
    ↓                     │
3 (Public endpoint) ──────┤ can run in parallel after 1
    ↓                     │
4 (Token API) ────────────┘
    ↓
5 (Frontend API)
    ↓
6 (Frontend UI)
    ↓
7 (Cleanup)
    ↓
8 (Testing)
```

## Key Files Modified

### Backend
- `src/backend/core/models.py` - CalendarSubscriptionToken model (standalone)
- `src/backend/core/migrations/0002_calendarsubscriptiontoken.py`
- `src/backend/core/api/serializers.py` - Token serializers
- `src/backend/core/api/viewsets.py` - SubscriptionTokenViewSet
- `src/backend/core/api/viewsets_ical.py` - ICalExportView
- `src/backend/core/urls.py` - Route registration
- `src/backend/core/admin.py` - Admin configuration
- `src/backend/core/factories.py` - Test factory

### Frontend
- `src/features/calendar/api.ts` - API functions with caldavPath
- `src/features/calendar/hooks/useCalendars.ts` - React Query hooks
- `src/features/calendar/components/calendar-list/CalendarList.tsx`
- `src/features/calendar/components/calendar-list/SubscriptionUrlModal.tsx`

### SabreDAV
- `docker/sabredav/server.php` - ICSExportPlugin enabled
