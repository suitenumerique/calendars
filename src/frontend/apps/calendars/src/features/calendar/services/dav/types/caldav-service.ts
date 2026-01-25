/**
 * Types for CalDavService - Pure CalDAV operations
 *
 * Reuses types from tsdav and ts-ics where possible to avoid duplication.
 */

import type { DAVCalendar, DAVCalendarObject } from 'tsdav'
import type {
  IcsCalendar,
  IcsEvent,
  IcsAttendee,
  IcsOrganizer,
  IcsAttendeePartStatusType,
  FreeBusyType as IcsFreeBusyType,
} from 'ts-ics'

// ============================================================================
// Re-exports from libraries (avoid duplication)
// ============================================================================

/** Attendee type from ts-ics */
export type CalDavAttendee = IcsAttendee

/** Organizer type from ts-ics */
export type CalDavOrganizer = IcsOrganizer

/** Attendee participation status from ts-ics */
export type AttendeeStatus = IcsAttendeePartStatusType

/** FreeBusy type from ts-ics */
export type FreeBusyType = IcsFreeBusyType

// ============================================================================
// Connection & Authentication
// ============================================================================

export type CalDavCredentials = {
  serverUrl: string
  username?: string
  password?: string
  headers?: Record<string, string>
  fetchOptions?: RequestInit
}

export type CalDavAccount = {
  serverUrl: string
  rootUrl?: string
  principalUrl?: string
  homeUrl?: string
  headers?: Record<string, string>
  fetchOptions?: RequestInit
}

// ============================================================================
// Calendar Types (extends tsdav types)
// ============================================================================

/** Calendar type extending DAVCalendar with additional properties */
export type CalDavCalendar = Pick<DAVCalendar, 'url' | 'ctag' | 'syncToken' | 'components' | 'timezone'> & {
  displayName: string
  description?: string
  color?: string
  resourcetype?: string[]
  headers?: Record<string, string>
  fetchOptions?: RequestInit
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
}

// ============================================================================
// Event Types (extends tsdav types)
// ============================================================================

/** Event type extending DAVCalendarObject with parsed ICS data */
export type CalDavEvent = Pick<DAVCalendarObject, 'url' | 'etag'> & {
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
// Sharing Types (CalDAV Scheduling & ACL)
// ============================================================================

export type SharePrivilege = 'read' | 'read-write' | 'read-write-noacl' | 'admin'

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
  summary?: string
  comment?: string
}

export type CalDavShareResponse = {
  success: boolean
  sharees: CalDavSharee[]
  errors?: { href: string; error: string }[]
}

export type CalDavInvitation = {
  uid: string
  calendarUrl: string
  ownerHref: string
  ownerDisplayName?: string
  summary?: string
  privilege: SharePrivilege
  status: ShareStatus
}

// ============================================================================
// Scheduling (iTIP) Types
// ============================================================================

export type SchedulingMethod = 'REQUEST' | 'REPLY' | 'CANCEL' | 'ADD' | 'REFRESH' | 'COUNTER' | 'DECLINECOUNTER'

export type SchedulingRequest = {
  method: SchedulingMethod
  organizer: CalDavOrganizer
  attendees: CalDavAttendee[]
  event: IcsEvent
}

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

export type FreeBusyPeriod = {
  start: Date
  end: Date
  type: FreeBusyType
}

export type FreeBusyRequest = {
  attendees: string[] // email addresses
  timeRange: TimeRange
  organizer?: CalDavOrganizer
}

export type FreeBusyResponse = {
  attendee: string
  periods: FreeBusyPeriod[]
}

// ============================================================================
// ACL Types
// ============================================================================

export type AclPrivilege =
  | 'all'
  | 'read'
  | 'write'
  | 'write-properties'
  | 'write-content'
  | 'unlock'
  | 'bind'
  | 'unbind'
  | 'read-acl'
  | 'write-acl'
  | 'read-current-user-privilege-set'

export type AclPrincipal = {
  href?: string
  all?: boolean
  authenticated?: boolean
  unauthenticated?: boolean
  self?: boolean
}

export type AclEntry = {
  principal: AclPrincipal
  privileges: AclPrivilege[]
  grant: boolean
  protected?: boolean
  inherited?: string
}

export type CalendarAcl = {
  calendarUrl: string
  entries: AclEntry[]
  ownerHref?: string
}

// ============================================================================
// Sync Types
// ============================================================================

export type SyncReport = {
  syncToken: string
  changed: CalDavEvent[]
  deleted: string[] // URLs of deleted events
}

export type SyncOptions = {
  syncToken?: string
  syncLevel?: 1 | 'infinite'
}

// ============================================================================
// Principal Types
// ============================================================================

export type CalDavPrincipal = {
  url: string
  displayName?: string
  email?: string
  calendarHomeSet?: string
  addressBookHomeSet?: string
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

export type CalDavMultiResponse<T> = {
  success: boolean
  results: { url: string; data?: T; error?: string }[]
}
