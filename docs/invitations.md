# Invitations

How event invitations work end-to-end: creating, sending, responding,
updating, and cancelling.

## Architecture

```
Frontend (EventModal)
  → CalDAV proxy (Django)
    → SabreDAV (stores event, detects attendees)
      → HttpCallbackIMipPlugin (HTTP POST to Django)
        → CalendarInvitationService (sends email)
          → Attendee receives email
            → RSVP link or iTIP client response
              → RSVPConfirmView (Django) or CalDAV REPLY
                → PARTSTAT updated in event
                  → Organizer notified (CalDAV REPLY path only)
```

## Creating an event with attendees

1. User adds attendees via `AttendeesSection` in EventModal
2. `useEventForm.toIcsEvent()` serializes the event with `ATTENDEE`
   and `ORGANIZER` properties
3. `CalDavService.createEvent()` sends a PUT to CalDAV through the
   Django proxy
4. SabreDAV uses its `CALDAV_CALLBACK_BASE_URL` env var to call
   back to Django

The resulting `.ics` contains:

```ics
BEGIN:VEVENT
UID:abc-123
SUMMARY:Team Meeting
DTSTART:20260301T140000Z
DTEND:20260301T150000Z
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:bob@example.com
SEQUENCE:0
END:VEVENT
```

## SabreDAV processing

When SabreDAV receives the event, three plugins run in order:

1. **CalendarSanitizerPlugin** (priority 85) — strips inline binary
   attachments (Outlook signatures), truncates oversized fields,
   enforces max resource size (1 MB default)
2. **AttendeeNormalizerPlugin** (priority 90) — lowercases emails,
   deduplicates attendees keeping the highest-priority PARTSTAT
   (ACCEPTED > TENTATIVE > DECLINED > NEEDS-ACTION)
3. **iMip scheduling** — detects attendees and creates a REQUEST
   message for each one

The scheduling message is routed by **HttpCallbackIMipPlugin**, which
POSTs to Django:

```
POST /api/v1.0/caldav-scheduling-callback/
X-LS-Api-Key: <shared secret>
X-LS-Sender: alice@example.com
X-LS-Recipient: bob@example.com
X-LS-Method: REQUEST
Content-Type: text/calendar

<serialized VCALENDAR>
```

## Sending invitation emails

`CalDAVSchedulingCallbackView` receives the callback and delegates to
`CalendarInvitationService.send_invitation()`.

Steps:

1. **Parse** — `ICalendarParser.parse()` extracts UID, summary,
   dates, organizer, attendee, location, description, sequence number
2. **Template selection** based on method and sequence:
   | Method | Sequence | Template |
   |--------|----------|----------|
   | REQUEST | 0 | `calendar_invitation.html` |
   | REQUEST | >0 | `calendar_invitation_update.html` |
   | CANCEL | any | `calendar_invitation_cancel.html` |
   | REPLY | any | `calendar_invitation_reply.html` |
3. **RSVP tokens** — for REQUEST emails, generates signed URLs:
   ```
   {APP_URL}/rsvp/?t=<signed>
   ```
   The email has one link per action (accepted, tentative, declined).
   `django.core.signing.TimestampSigner(salt="rsvp")` signs the token.
   The token contains
   `{u: uid, e: email, o: organizer, g: org id, a: action}`.
4. **ICS attachment** — if `CALENDAR_ITIP_ENABLED=True`, the
   attachment includes `METHOD:REQUEST` for iTIP-aware clients
   (Outlook, Apple Mail). If False (default), the METHOD is stripped
   and web RSVP links are used instead.
5. **Send** — multipart email with HTML + plain text + ICS attachment.
   Reply-To is set to the organizer's email.

## Responding to invitations

Two paths:

### Web RSVP (default)

Attendee clicks Accept / Maybe / Decline link in the email.

`RSVPConfirmView` handles `/rsvp/`:

1. `GET /rsvp/?t=...` renders a page that sends the POST with
   JavaScript. Without JavaScript, the page shows a submit button.
   GET-only previewers do not submit an RSVP.
2. `POST /rsvp/` checks the token signature (salt="rsvp")
3. The view calls `POST /internal-api/rsvp/` on SabreDAV. SabreDAV
   sets the attendee's `PARTSTAT` to ACCEPTED, TENTATIVE or DECLINED
4. The view renders a confirmation page

The internal API writes the event directly to the CalDAV backend.
SabreDAV scheduling does not run. As a result, SabreDAV sends no
REPLY and the organizer gets no email.

### iTIP client response

When `CALENDAR_ITIP_ENABLED=True`, email clients like Outlook or
Apple Calendar show native Accept/Decline buttons. The client sends
an iTIP REPLY directly to the CalDAV server, which triggers the same
callback flow.

## Updating an event

When an event with attendees is modified:

1. `CalDavService.updateEvent()` increments the `SEQUENCE` number
2. SabreDAV detects the change and creates REQUEST messages with the
   updated sequence
3. Attendees receive an update email
   (`calendar_invitation_update.html`)

## Cancelling an event

When an event with attendees is deleted:

1. SabreDAV creates CANCEL messages for each attendee
2. Attendees receive a cancellation email
   (`calendar_invitation_cancel.html`)

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `CALDAV_URL` | `http://caldav:80` | Internal CalDAV server URL |
| `CALDAV_INBOUND_API_KEY` | None | API key for callbacks from CalDAV |
| `CALDAV_OUTBOUND_API_KEY` | None | API key for requests to CalDAV |
| `CALDAV_CALLBACK_BASE_URL` | **required** | Base URL for CalDAV→Django callbacks (e.g. `http://backend:8000`). Set on the CalDAV container. |
| `CALENDAR_ITIP_ENABLED` | False | Use iTIP METHOD headers in ICS attachments |
| `CALENDAR_INVITATION_FROM_EMAIL` | `DEFAULT_FROM_EMAIL` | Sender address for invitation emails |
| `APP_URL` | `""` | Public URL of the backend. Required: the RSVP links and the images in emails are built from it |
| `EMAIL_LOGO_IMG` | `None` | URL of the logo in emails. Empty: the Calendriers logo from `APP_URL/static/images/` |
| `EMAIL_FOOTER_IMG` | `None` | URL of the footer image in emails, shown 160px wide. Empty: no footer |

## Key files

| Area | Path |
|------|------|
| Attendee UI | `src/frontend/.../event-modal-sections/AttendeesSection.tsx` |
| Event form | `src/frontend/.../scheduler/hooks/useEventForm.ts` |
| CalDAV client | `src/frontend/.../services/dav/CalDavService.ts` |
| CalDAV proxy | `src/backend/core/api/viewsets_caldav.py` |
| Scheduling callback | `src/backend/core/api/viewsets_caldav.py` (`CalDAVSchedulingCallbackView`) |
| RSVP handler | `src/backend/core/api/viewsets_rsvp.py` |
| Email service | `src/backend/core/services/calendar_invitation_service.py` |
| ICS parser | `src/backend/core/services/calendar_invitation_service.py` (`ICalendarParser`) |
| Email templates | `src/backend/core/templates/emails/calendar_invitation*.html` |
| Email images | `src/backend/core/static/images/` (served from `APP_URL/static/images/`) |
| SabreDAV sanitizer | `src/caldav/src/CalendarSanitizerPlugin.php` |
| SabreDAV attendee dedup | `src/caldav/src/AttendeeNormalizerPlugin.php` |
| SabreDAV callback plugin | `src/caldav/src/HttpCallbackIMipPlugin.php` |

## Future: Messages mail client integration

La Suite includes a Messages mail client (based on an open-source
webmail). Future integration would allow:

- **Inline RSVP** — render Accept/Decline buttons directly in the
  Messages UI when an email contains a `text/calendar` attachment with
  `METHOD:REQUEST`
- **Calendar preview** — show event details (date, time, location)
  extracted from the ICS attachment without opening the full calendar
- **Auto-add to calendar** — accepted events automatically appear in
  the user's Calendars calendar via a shared CalDAV backend
- **Status sync** — PARTSTAT changes in Messages propagate to
  Calendars and vice versa

This requires Messages to support iTIP processing
(`CALENDAR_ITIP_ENABLED=True`) and share the same CalDAV/auth
infrastructure.
