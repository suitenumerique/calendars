# Design: iCal Subscription Export

## Context

La Suite Calendars uses SabreDAV as its CalDAV server, but the current
authentication model (API key + X-Forwarded-User headers) prevents direct
access from external calendar clients. Users need a way to subscribe to their
calendars from applications like Apple Calendar, Google Calendar, etc.

SabreDAV provides an `ICSExportPlugin` that generates RFC 5545 compliant iCal
files. We want to leverage this plugin while providing a clean, unauthenticated
URL for external calendar applications.

## Goals / Non-Goals

**Goals:**
- Allow users to subscribe to their calendars from external applications
- Per-calendar subscription URLs with private tokens
- Clean URL format similar to Google Calendar / Outlook
- Ability to revoke/regenerate tokens
- Reuse SabreDAV's ICSExportPlugin for ICS generation
- **Standalone tokens that don't require synchronizing CalDAV calendars with Django**

**Non-Goals:**
- Write access from external clients (read-only subscriptions)
- Full CalDAV protocol support for external clients
- Importing external calendars into La Suite Calendars (future feature)
- Real-time sync (clients poll at their own refresh rate)

## Decisions

### 1. URL Format

**Decision:** Use a short, clean URL with token in the path:

```
https://<domain>/ical/<uuid-token>.ics
```

**Examples from other services:**
- Google: `https://calendar.google.com/calendar/ical/<id>/public/basic.ics`
- Outlook: `https://outlook.office365.com/owa/calendar/<id>/<id>/calendar.ics`

**Rationale:**
- Industry standard format
- No authentication prompt in calendar apps (token IS the auth)
- Easy to copy/paste
- Token not exposed in query strings (cleaner logs)

### 2. Django Proxy to SabreDAV

**Decision:** Django handles the public endpoint and proxies to SabreDAV.

```
Apple Calendar
      │
      │ GET /ical/<token>.ics (no auth headers)
      ▼
  Django (public endpoint)
      │
      │ 1. Extract token from URL
      │ 2. Lookup CalendarSubscriptionToken in DB
      │ 3. Get caldav_path and owner.email directly from token
      ▼
  Django → SabreDAV (internal)
      │
      │ GET /calendars/<owner>/<calendar>?export
      │ Headers: X-Api-Key, X-Forwarded-User
      ▼
  SabreDAV ICSExportPlugin
      │
      │ Generates RFC 5545 ICS
      ▼
  Django returns ICS to client
```

**Rationale:**
- No changes to SabreDAV authentication backend
- Clean separation: Django handles tokens, SabreDAV handles CalDAV
- Token validation logic stays in Python (easier to test/maintain)
- Reuses existing CalDAV proxy infrastructure

### 3. Token Storage - Standalone Model

**Decision:** Django model `CalendarSubscriptionToken` is **standalone** and stores the CalDAV path directly:

```python
class CalendarSubscriptionToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Owner of the calendar (for permission verification)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription_tokens",
    )

    # CalDAV path stored directly (e.g., /calendars/user@example.com/uuid/)
    caldav_path = models.CharField(max_length=512)

    # Calendar display name (for UI and filename)
    calendar_name = models.CharField(max_length=255, blank=True, default="")

    token = models.UUIDField(unique=True, db_index=True, default=uuid.uuid4)
    is_active = models.BooleanField(default=True)
    last_accessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "caldav_path"],
                name="unique_token_per_owner_calendar",
            )
        ]
```

**Rationale:**
- **No dependency on Django Calendar model** - tokens work directly with CalDAV paths
- No need to synchronize CalDAV calendars to Django before creating tokens
- Works for all calendars (not just those previously synced to Django)
- Avoids fragile name-matching when multiple calendars have the same name
- UUID provides 128 bits of entropy (secure)
- `is_active` allows soft-disable without deletion
- `last_accessed_at` for auditing
- Unique constraint ensures one token per user+calendar combination

### 4. Token Scope: Per Calendar Path

**Decision:** One token per user + CalDAV path combination.

**Rationale:**
- Users can share specific calendars without exposing all calendars
- Revoking one calendar's access doesn't affect others
- Permission verification via path: user's email must be in the CalDAV path

### 5. Permission Verification via CalDAV Path

**Decision:** Verify ownership by checking the user's email is in the CalDAV path.

```python
def _verify_caldav_access(self, user, caldav_path):
    # Path format: /calendars/user@example.com/uuid/
    parts = caldav_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "calendars":
        path_email = unquote(parts[1])
        return path_email.lower() == user.email.lower()
    return False
```

**Rationale:**
- CalDAV paths inherently contain the owner's email
- No need to query CalDAV server to check permissions
- Simple and fast verification

### 6. ICS Generation via SabreDAV

**Decision:** Use SabreDAV's `ICSExportPlugin` instead of generating ICS in
Django.

**Rationale:**
- ICSExportPlugin is battle-tested and RFC 5545 compliant
- Handles recurring events, timezones, and edge cases correctly
- No code duplication
- SabreDAV already has the calendar data

**Required change in `server.php`:**
```php
$server->addPlugin(new CalDAV\ICSExportPlugin());
```

## API Design

### Public Endpoint (no authentication)

```
GET /ical/<uuid>.ics
    → Validates token
    → Proxies to SabreDAV using token.caldav_path and token.owner.email
    → Returns ICS (Content-Type: text/calendar)
    → 404 if token invalid/inactive
```

### Token Management (authenticated Django API)

**New standalone endpoint:**

```
POST   /api/v1.0/subscription-tokens/
       Body: { caldav_path, calendar_name (optional) }
       → Creates token or returns existing (owner only)
       → Verifies user's email is in caldav_path
       → Returns: { token, url, caldav_path, calendar_name, created_at }

GET    /api/v1.0/subscription-tokens/by-path/?caldav_path=...
       → Returns existing token or 404

DELETE /api/v1.0/subscription-tokens/by-path/?caldav_path=...
       → Deletes token (revokes access)
```

### Frontend Flow

1. User clicks "Get subscription URL" on a calendar
2. Frontend extracts CalDAV path from the calendar's URL
3. Frontend calls `POST /subscription-tokens/` with `{ caldav_path, calendar_name }`
4. Backend creates token (or returns existing) and returns subscription URL
5. Modal displays URL with copy button

## Security Considerations

### Token as Secret

- Token is a UUID (128 bits of entropy) - infeasible to brute force
- Knowledge of token = read access to calendar
- URL should be treated as confidential

### Mitigations

- Clear UI warning about URL privacy
- Easy token regeneration (delete + create)
- `last_accessed_at` tracking for auditing
- Rate limiting on `/ical/` endpoint (future)

### Attack Surface

- Token in URL may appear in:
  - Server access logs → configure log rotation, mask tokens
  - Browser history (if opened in browser) → minor concern
  - Referrer headers → set `Referrer-Policy: no-referrer`
- No CSRF risk (read-only, no state changes via GET)

## Implementation Notes

### Django View for /ical/<token>.ics

```python
class ICalExportView(View):
    def get(self, request, token):
        # 1. Lookup token
        subscription = CalendarSubscriptionToken.objects.filter(
            token=token, is_active=True
        ).select_related('owner').first()

        if not subscription:
            raise Http404

        # 2. Update last_accessed_at
        subscription.last_accessed_at = timezone.now()
        subscription.save(update_fields=['last_accessed_at'])

        # 3. Proxy to SabreDAV using caldav_path and owner directly
        caldav_path = subscription.caldav_path.lstrip("/")
        caldav_url = f"{settings.CALDAV_URL}/api/v1.0/caldav/{caldav_path}?export"

        response = requests.get(
            caldav_url,
            headers={
                'X-Api-Key': settings.CALDAV_OUTBOUND_API_KEY,
                'X-Forwarded-User': subscription.owner.email,
            }
        )

        # 4. Return ICS
        display_name = subscription.calendar_name or "calendar"
        return HttpResponse(
            response.content,
            content_type='text/calendar',
            headers={
                'Content-Disposition': f'attachment; filename="{display_name}.ics"',
                'Cache-Control': 'no-store, private',
                'Referrer-Policy': 'no-referrer',
            }
        )
```

### URL Configuration

```python
# urls.py
urlpatterns = [
    path('ical/<uuid:token>.ics', ICalExportView.as_view(), name='ical-export'),
]
```

## Risks / Trade-offs

### Trade-off: Extra HTTP Hop

Django proxies to SabreDAV (local network call).
- **Pro:** Clean architecture, no PHP changes
- **Con:** Slight latency (~1-5ms on localhost)
- **Verdict:** Acceptable for a polling use case (clients refresh hourly)

### Risk: Token Leakage

If URL is shared/leaked, anyone can read the calendar.
- **Mitigation:** Regenerate token feature, access logging, UI warnings

### Risk: Large Calendar Performance

Generating ICS for calendars with thousands of events.
- **Mitigation:** SabreDAV handles this efficiently
- **Future:** Add date range filtering (`?start=...&end=...`)

## Migration Plan

1. Add `CalendarSubscriptionToken` Django model with standalone fields
2. Create migration (adds owner, caldav_path, calendar_name fields)
3. Add `ICSExportPlugin` to SabreDAV `server.php`
4. Create Django `/ical/<token>.ics` endpoint
5. Add standalone `SubscriptionTokenViewSet` API
6. Update frontend to use caldav_path instead of calendar ID
7. No data migration needed (new feature)

## References

- [SabreDAV ICSExportPlugin](https://sabre.io/dav/ics-export-plugin/)
- [Google Calendar public URL format](https://support.google.com/calendar/answer/37083)
- [Outlook calendar publishing](https://support.microsoft.com/en-us/office/introduction-to-publishing-internet-calendars-a25e68d6-695a-41c6-a701-103d44ba151d)
