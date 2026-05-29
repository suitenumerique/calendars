/**
 * Types for CalDavService - Pure CalDAV operations
 *
 * Reuses types from ts-ics where possible to avoid duplication.
 */

import type {
  IcsCalendar,
  IcsEvent,
  IcsAttendee,
} from 'ts-ics'

/** Attendee type from ts-ics */
export type CalDavAttendee = IcsAttendee

// ============================================================================
// Connection & Authentication
// ============================================================================

export type CalDavCredentials = {
  serverUrl: string
  // SabreDAV's principal/home URLs are derived from this:
  //   principals/users/<email>, calendars/users/<email>.
  userEmail: string
}

export type CalDavAccount = {
  serverUrl: string
  principalUrl: string
  homeUrl: string
}

// ============================================================================
// Calendar Types
// ============================================================================

/** Calendar resource on the CalDAV server. */
export type CalDavCalendar = {
  url: string
  ctag?: string
  syncToken?: string
  components?: string[]
  timezone?: string
  displayName: string
  description?: string
  color?: string
  /**
   * `{http://apple.com/ns/ical/}calendar-order`. Integer used to manually
   * sort calendars in the sidebar. Undefined when the calendar has never
   * been reordered.
   */
  order?: number
  /** Whether this calendar's events count toward freebusy (default: true) */
  includeInAvailability: boolean
  /** Owner principal type: "MAILBOX" for mailbox calendars, undefined otherwise */
  ownerType?: string
  /**
   * Email of the owning mailbox principal, parsed from the
   * ``CS:invite/CS:organizer`` href returned by SabreDAV. Only set when
   * ``ownerType === "MAILBOX"``. Available immediately on every
   * calendar fetch — does not depend on mailbox-context hydration.
   */
  mailboxEmail?: string
  /**
   * Sharees parsed from the ``CS:invite`` payload returned alongside
   * the standard calendar properties. The share modal reads this
   * directly instead of issuing a second PROPFIND.
   */
  sharees?: CalDavSharee[]
  resourcetype?: string[]
}

export type CalDavCalendarCreate = {
  displayName: string
  description?: string
  color?: string
  timezone?: string
  components?: ('VEVENT' | 'VTODO' | 'VJOURNAL')[]
}

export type CalDavCalendarUpdate = {
  displayName?: string
  description?: string
  color?: string
  timezone?: string
  /** Toggle whether this calendar counts toward freebusy/availability */
  includeInAvailability?: boolean
  /** `calendar-order` for manual sidebar ordering. */
  order?: number
}

// ============================================================================
// Event Types
// ============================================================================

/** Event resource with parsed ICS data. */
export type CalDavEvent = {
  url: string
  etag?: string
  calendarUrl: string
  data: IcsCalendar
}

export type CalDavEventCreate = {
  calendarUrl: string
  event: IcsEvent
}

export type CalDavEventUpdate = {
  eventUrl: string
  event: IcsEvent
  etag?: string
}

export type CalDavEventMove = {
  sourceEventUrl: string
  targetCalendarUrl: string
  sourceEtag?: string
}

// ============================================================================
// Time Range & Filters
// ============================================================================

export type TimeRange = {
  start: string | Date
  end: string | Date
}

export type EventFilter = {
  timeRange?: TimeRange
  expand?: boolean
  componentType?: 'VEVENT' | 'VTODO' | 'VJOURNAL'
}

// ============================================================================
// Sharing Types
// ============================================================================

export type SharePrivilege = 'freebusy' | 'read' | 'read-write' | 'admin'

export type ShareStatus = 'pending' | 'accepted' | 'declined'

export type CalDavSharee = {
  href: string // mailto:email or principal URL
  displayName?: string
  privilege: SharePrivilege
  status?: ShareStatus
}

export type CalDavShareInvite = {
  calendarUrl: string
  sharees: CalDavSharee[]
}

export type CalDavShareResponse = {
  success: boolean
  sharees: CalDavSharee[]
  errors?: { href: string; error: string }[]
}

// ============================================================================
// Scheduling (iTIP) Types — used by respondToMeeting
// ============================================================================

export type SchedulingResponse = {
  success: boolean
  responses: {
    recipient: string
    status: 'delivered' | 'failed' | 'pending'
    error?: string
  }[]
}

// ============================================================================
// FreeBusy Types
// ============================================================================

export type FreeBusyRequest = {
  attendees: string[] // email addresses
  timeRange: TimeRange
  organizer?: { email: string; name?: string }
}

export type FreeBusyResponse = {
  attendee: string
  periods: {
    start: Date
    end: Date
    type: string
  }[]
}

// ============================================================================
// Response Types
// ============================================================================

export type CalDavResponse<T = void> = {
  success: boolean
  data?: T
  error?: string
  status?: number
}
