# Changelog

All notable changes to this project will be documented in this
file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-12

### Added

- Silent login for visitors with an SSO session
  (`FRONTEND_SILENT_LOGIN_ENABLED`, off by default) #98
- Hide a shared calendar and keep the access: the calendar is hidden in the
  web app and in the user's CalDAV clients, and a CalDAV client that deletes a
  mailbox calendar now hides it #119
- Leave a shared calendar, from the sidebar or from Settings › Calendars,
  with a dialog that tells the sharee they lose only their own access #110 #145
- Allow mailbox admins to delete a mailbox calendar for every user #73
- Keep the last calendar view across reloads and logins #121
- Show the end time on the event chip for events longer than 30 minutes #120
- Error screen with a reload button for unexpected application errors #76
- Support Chromium 109 (last Windows 7 build) with polyfills, and fall back to
  UTC when the browser does not know a timezone #96

### Changed

- Show all calendars in one list in the sidebar and in the settings: mailbox
  calendars no longer sit under "My calendars" #145
- Restyle the invitation, update, cancel and reply emails to the La Suite
  charter, with RSVP buttons that fit on a phone #125
- Translate the remaining English texts for French and Dutch users: "+N more",
  share errors, toasts, labels and dates #106
- Show the RSVP pages in the attendee's saved language, else the browser
  language #138
- The language picker lists the `LANGUAGES` of the instance config #141
- Replace pnpm with npm for the frontend #96
- Move the backend to Python 3.14 and the CalDAV server to PHP 8.5, and pin
  all images by digest #100
- Upgrade Django REST framework to 3.18, Pillow to 13, PyJWT to 2.15 and
  requests to 2.34

### Fixed

- An RSVP no longer restores an event that the organizer cancelled or deleted,
  nor an attendee that the organizer removed #113
- Accepting one occurrence of a recurring event no longer sends a decline to
  the organizer #134
- A read-only sharee gets the event body on a CalDAV GET again: the RSVP
  modal no longer says that the event is gone #135
- Name the attendee, not the organizer, in reply emails #133
- Share a calendar with every user selected in the share dialog, not only the
  first one #132
- A deleted mailbox calendar no longer comes back after a refresh: deleting a
  sync-managed instance is refused #109
- Allow a mailbox admin from another organization to delete a mailbox
  calendar #130
- Add a CalDAV account from macOS and iOS: plain OPTIONS requests reach the
  CalDAV server #97
- Keep settings rows in place when a calendar is hidden, and show the address
  of each mailbox calendar #137
- The language picker shows the UI language for users who never chose one #131
- Show the calendar creation prompt to users who have only shared
  calendars #115
- Hide the Messages text in the onboarding when the Messages integration is
  off #114
- Fix the layout of the link list in the mobile drawer #122
- Open the Messages widget from the feedback button #68
- Remove the hardcoded `lang=en` that made browsers offer to translate the page
- Calendar color consistency, special-character escaping and user search
  beyond 50 results #76

### Security

- Check write access on event import: only the owner and read-write sharees
  can import, and the menu hides the import on read-only calendars #143
- API errors send a stable code and a fixed text, and no longer expose server
  internals (CalDAV host and path, internal API status, settings names) #106
- Prevent sharees from updating the properties of a shared calendar #76
- Upgrade PHP to 8.5.12 in the CalDAV image #101

## [0.1.0] - 2026-06-18

First public release.

[unreleased]: https://github.com/suitenumerique/calendars/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/suitenumerique/calendars/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/suitenumerique/calendars/releases/tag/v0.1.0
