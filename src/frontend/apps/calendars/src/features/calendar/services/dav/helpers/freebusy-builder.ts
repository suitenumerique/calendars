/**
 * VFREEBUSY request builder for CalDAV scheduling outbox queries.
 *
 * Wraps ts-ics's structured ``generateIcsCalendar`` so the wire bytes
 * are produced by a real RFC 5545 generator instead of a hand-built
 * template literal.
 *
 * History: this used to be a hand-built template literal in
 * ``CalDavService.queryFreeBusy``. The previous shape was:
 *
 *   const attendeeLines = request.attendees
 *     .map((email) => `ATTENDEE:mailto:${email}`)
 *     .join('\n')
 *   const fbRequest = `BEGIN:VCALENDAR
 *   …
 *   ${attendeeLines}
 *   …`
 *
 * Two problems with that approach:
 *  1. ``email`` is interpolated into a property line with no escaping,
 *     so an email containing CR/LF would line-inject a new property.
 *     The threat surface today is "user attacks themselves" (the user
 *     picks the attendee from their own UI), but that's a fragile
 *     property to rely on.
 *  2. The hand-built template doesn't fold long lines per RFC 5545,
 *     doesn't escape special chars in property values, and doesn't
 *     guarantee canonical line endings — meaning sabre/dav has to
 *     "fix" the bytes on receipt every time.
 *
 * Both go away by going through ts-ics's generator, which produces
 * canonical RFC 5545 output and rejects malformed inputs at build
 * time.
 */
import { generateIcsCalendar, type IcsCalendar, type IcsFreeBusy } from 'ts-ics'
import type { FreeBusyRequest } from '../types/caldav-service'

/**
 * Validate that an email string is free of control characters.
 *
 * RFC 5322 forbids CR, LF, NUL and other C0 control characters in
 * email addresses. We enforce that here at the boundary because:
 *
 *  1. ts-ics's ``generateIcsCalendar`` does NOT escape control chars
 *     in property values — it interpolates them verbatim. Passing
 *     ``alice@x\nMETHOD:CANCEL`` produces a calendar with a smuggled
 *     ``METHOD:CANCEL`` line. The hand-built template literal we
 *     replaced had the same bug; switching to ts-ics did not fix it.
 *
 *  2. The threat model is "user attacks themselves" today (the user
 *     picks attendees from their own address book), but a hard input
 *     gate at the boundary is the only way to keep that property
 *     stable across future refactors that might surface a different
 *     attendee source — e.g. an "import attendees from CSV" feature.
 *
 * Throws ``InvalidFreeBusyEmailError`` instead of silently sanitizing
 * because a hostile email is never a legitimate input — it's either a
 * bug upstream or an attack — and we want loud failure, not quiet
 * mangling.
 */
const CONTROL_CHARS = /[\x00-\x1f\x7f]/
function assertSafeEmail(email: string, role: string): void {
  if (CONTROL_CHARS.test(email)) {
    throw new InvalidFreeBusyEmailError(
      `${role} email contains control characters and cannot be used in a CalDAV freebusy request`,
    )
  }
}

export class InvalidFreeBusyEmailError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'InvalidFreeBusyEmailError'
  }
}

/**
 * Build a VFREEBUSY scheduling request ICS body.
 *
 * Returns a fully-canonical iCalendar string ready to POST to the
 * CalDAV scheduling outbox.
 *
 * Throws ``InvalidFreeBusyEmailError`` if any attendee or organizer
 * email contains control characters (CR/LF/NUL/etc.) that would
 * line-inject into the generated ICS body.
 */
export function buildFreeBusyRequestIcs(request: FreeBusyRequest): string {
  // Validate every email BEFORE building the calendar so the throw
  // happens at a single, easy-to-trace point. Validation is cheap.
  for (const email of request.attendees) {
    assertSafeEmail(email, 'attendee')
  }
  if (request.organizer) {
    assertSafeEmail(request.organizer.email, 'organizer')
  }

  const startDate =
    typeof request.timeRange.start === 'string'
      ? new Date(request.timeRange.start)
      : request.timeRange.start
  const endDate =
    typeof request.timeRange.end === 'string'
      ? new Date(request.timeRange.end)
      : request.timeRange.end

  const freeBusy: IcsFreeBusy = {
    // RFC 5545 requires DTSTAMP and UID on every component.
    stamp: { date: new Date(), type: 'DATE-TIME' },
    uid: `freebusy-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    start: { date: startDate, type: 'DATE-TIME' },
    end: { date: endDate, type: 'DATE-TIME' },
    attendees: request.attendees.map((email) => ({ email })),
    ...(request.organizer ? { organizer: { email: request.organizer.email } } : {}),
  }

  const fbCalendar: IcsCalendar = {
    version: '2.0',
    prodId: '-//CalDavService//NONSGML v1.0//EN',
    method: 'REQUEST',
    freeBusy: [freeBusy],
  }

  return generateIcsCalendar(fbCalendar)
}
