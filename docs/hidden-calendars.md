# Hidden Calendars

A user can hide a calendar that they do not own, for example a
calendar that a colleague shares with them or a mailbox calendar. The
user keeps their access. The calendar no longer shows in the web app
or in the user's CalDAV clients.

The web app offers "Hide this calendar" in the calendar menu. The page
Settings › Calendars (`/settings/calendars`) lists all the calendars of
the user, hidden ones included, and shows them again. The page also
lets the user delete a calendar they own, or leave a calendar that a
colleague shares with them.

Hiding is not the checkbox of the sidebar. The checkbox only changes
the display in one browser.

## How it works

- **Storage**: the `LS:calendar-hidden` property (value `true`) on the
  user's own instance of the calendar. The web app sets and removes it
  with a `PROPPATCH`. PropertyStorage stores it by path, so each user
  has their own value. `HiddenCalendarPlugin` accepts it only on a
  sharee instance; an owner deletes their calendar instead. The value
  can stay after the instance is deleted, because most deletes skip
  PropertyStorage. This has no effect: a new instance always gets a new
  URI.
- **Listing**: a `PROPFIND` on the calendar home leaves hidden calendars
  out, so CalDAV clients stop showing them and their reminders. Direct
  URLs still work. The web app sends `X-LS-Include-Hidden: true` to list
  them too. The Django CalDAV proxy forwards this header.
- **No other change**: the access, the owner's share list, the emails
  and the free/busy stay the same. See [freebusy.md](freebusy.md).

## Mailbox calendars

A user cannot delete their instance of a mailbox calendar, because the
next sync of Messages would create it again. A `DELETE` of this
instance hides the calendar and returns 204. CalDAV clients send this
`DELETE` when the user deletes the calendar.

The mailbox sync keeps the URI of an instance, so the calendar stays
hidden. When Messages removes the access and gives it back later, the
new instance has a new URI and shows again. See
[mailboxes.md](mailboxes.md).
