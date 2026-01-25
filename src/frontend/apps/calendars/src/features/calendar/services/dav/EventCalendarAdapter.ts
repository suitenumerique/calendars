/**
 * EventCalendarAdapter - Conversion service between CalDAV and EventCalendar formats
 *
 * This adapter provides bidirectional conversion between CalDAV data structures
 * (IcsEvent, CalDavCalendar, etc.) and EventCalendar (vkurko/calendar) format.
 *
 * EventCalendar: https://github.com/vkurko/calendar
 *
 * @example
 * ```ts
 * const adapter = new EventCalendarAdapter()
 *
 * // Convert CalDAV events to EventCalendar format
 * const ecEvents = adapter.toEventCalendarEvents(caldavEvents, { calendarColors })
 *
 * // Convert EventCalendar event back to CalDAV
 * const icsEvent = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Europe/Paris' })
 * ```
 */

import type { IcsCalendar, IcsDateObject, IcsEvent, IcsRecurrenceRule, IcsAttendee, IcsOrganizer, IcsDuration } from 'ts-ics'
import type { CalDavCalendar, CalDavEvent } from './types/caldav-service'
import type {
  EventCalendarEvent,
  EventCalendarEventInput,
  EventCalendarResource,
  EventCalendarDuration,
  CalDavToEventCalendarOptions,
  EventCalendarToCalDavOptions,
} from './types/event-calendar'

// Extended attendee/organizer types for UI display (has displayName instead of name)
type ExtendedAttendee = {
  email: string
  displayName?: string
  role?: IcsAttendee['role']
  status?: string
  rsvp?: boolean
}

type ExtendedOrganizer = {
  email: string
  displayName?: string
}

// ============================================================================
// Extended Types for conversion metadata
// ============================================================================

/**
 * Extended props stored in EventCalendarEvent.extendedProps
 * Contains original CalDAV data for round-trip conversion
 */
export type CalDavExtendedProps = {
  /** Original ICS UID */
  uid: string
  /** Calendar URL this event belongs to */
  calendarUrl: string
  /** Event URL for updates/deletes */
  eventUrl?: string
  /** ETag for optimistic concurrency */
  etag?: string
  /** Original recurrence rule */
  recurrenceRule?: IcsRecurrenceRule
  /** Recurrence ID for recurring event instances */
  recurrenceId?: Date
  /** Is this a recurring event instance */
  isRecurringInstance?: boolean
  /** Original timezone */
  timezone?: string
  /** Event sequence number */
  sequence?: number
  /** Event status */
  status?: string
  /** Event location */
  location?: string
  /** Event description */
  description?: string
  /** Event organizer */
  organizer?: ExtendedOrganizer
  /** Event attendees */
  attendees?: ExtendedAttendee[]
  /** Event categories/tags */
  categories?: string[]
  /** Event priority (1-9, 1 highest) */
  priority?: number
  /** Event URL */
  url?: string
  /** Creation timestamp */
  created?: Date
  /** Last modified timestamp */
  lastModified?: Date
  /** Custom X-properties */
  customProperties?: Record<string, string>
}

// ============================================================================
// EventCalendarAdapter Class
// ============================================================================

export class EventCalendarAdapter {
  private defaultOptions: CalDavToEventCalendarOptions = {
    defaultEventColor: '#3788d8',
    defaultTextColor: '#ffffff',
    includeRecurringInstances: true,
  }

  // ============================================================================
  // CalDAV -> EventCalendar Conversions
  // ============================================================================

  /**
   * Convert CalDAV events to EventCalendar format
   */
  public toEventCalendarEvents(
    caldavEvents: CalDavEvent[],
    options?: CalDavToEventCalendarOptions
  ): EventCalendarEvent[] {
    const opts = { ...this.defaultOptions, ...options }
    const events: EventCalendarEvent[] = []

    for (const caldavEvent of caldavEvents) {
      const icsEvents = caldavEvent.data.events ?? []

      // Build a map of source events (with recurrenceRule) by UID
      const sourceEventRules = new Map<string, IcsRecurrenceRule>()
      for (const icsEvent of icsEvents) {
        if (icsEvent.recurrenceRule && !icsEvent.recurrenceId) {
          sourceEventRules.set(icsEvent.uid, icsEvent.recurrenceRule)
        }
      }

      for (const icsEvent of icsEvents) {
        // Skip recurring source events if we only want instances
        if (icsEvent.recurrenceRule && !icsEvent.recurrenceId && !opts.includeRecurringInstances) {
          continue
        }

        // If this is a recurring instance without recurrenceRule, copy it from source
        const enrichedEvent = { ...icsEvent }
        if (icsEvent.recurrenceId && !icsEvent.recurrenceRule) {
          const sourceRule = sourceEventRules.get(icsEvent.uid)
          if (sourceRule) {
            enrichedEvent.recurrenceRule = sourceRule
          }
        }

        const ecEvent = this.icsEventToEventCalendarEvent(
          enrichedEvent,
          caldavEvent.calendarUrl,
          caldavEvent.url,
          caldavEvent.etag,
          opts
        )

        events.push(ecEvent)
      }
    }

    return events
  }

  /**
   * Convert a single IcsEvent to EventCalendarEvent
   */
  public icsEventToEventCalendarEvent(
    icsEvent: IcsEvent,
    calendarUrl: string,
    eventUrl?: string,
    etag?: string,
    options?: CalDavToEventCalendarOptions
  ): EventCalendarEvent {
    const opts = { ...this.defaultOptions, ...options }

    // Generate unique ID
    const id = opts.eventIdGenerator
      ? opts.eventIdGenerator(icsEvent, calendarUrl)
      : this.generateEventId(icsEvent)

    // Determine colors
    const calendarColor = opts.calendarColors?.get(calendarUrl)
    const backgroundColor = calendarColor ?? opts.defaultEventColor
    const textColor = opts.defaultTextColor

    // Convert dates
    const start = this.icsDateToJsDate(icsEvent.start)
    const end = icsEvent.end
      ? this.icsDateToJsDate(icsEvent.end)
      : icsEvent.duration
        ? this.addIcsDurationToDate(start, icsEvent.duration)
        : start

    // Determine if all-day event
    const allDay = icsEvent.start.type === 'DATE'

    // EventCalendar expects ISO strings but interprets them in browser local time
    // We need to create ISO strings that preserve the local time components
    // instead of using toISOString() which converts to UTC

    // Build extended props
    const extendedProps: CalDavExtendedProps = {
      uid: icsEvent.uid,
      calendarUrl,
      eventUrl,
      etag,
      recurrenceRule: icsEvent.recurrenceRule,
      recurrenceId: icsEvent.recurrenceId?.value.date,
      isRecurringInstance: !!icsEvent.recurrenceId,
      timezone: icsEvent.start.local?.timezone,
      sequence: icsEvent.sequence,
      status: icsEvent.status,
      location: icsEvent.location,
      description: icsEvent.description,
      organizer: icsEvent.organizer
        ? {
            email: icsEvent.organizer.email,
            displayName: icsEvent.organizer.name,
          }
        : undefined,
      attendees: this.deduplicateAttendees(icsEvent.attendees?.map((att) => ({
        email: att.email,
        displayName: att.name,
        role: att.role as ExtendedAttendee['role'],
        status: att.partstat as ExtendedAttendee['status'],
        rsvp: att.rsvp,
      }))),
      categories: icsEvent.categories,
      priority: icsEvent.priority != null ? Number(icsEvent.priority) : undefined,
      url: icsEvent.url,
      created: icsEvent.created ? this.icsDateToJsDate(icsEvent.created) : undefined,
      lastModified: icsEvent.lastModified ? this.icsDateToJsDate(icsEvent.lastModified) : undefined,
    }

    // Add any custom extended props
    if (opts.extendedPropsExtractor) {
      Object.assign(extendedProps, opts.extendedPropsExtractor(icsEvent))
    }

    return {
      id,
      start: allDay ? this.dateToDateOnlyString(start) : this.dateToLocalISOString(start),
      end: allDay ? this.dateToDateOnlyString(end) : this.dateToLocalISOString(end),
      allDay,
      resourceId: calendarUrl,
      resourceIds: [calendarUrl],
      title: icsEvent.summary ?? '',
      backgroundColor,
      textColor,
      editable: true,
      extendedProps,
    }
  }

  /**
   * Convert Date to date-only ISO string (YYYY-MM-DD)
   * For all-day events, use UTC components since the Date is UTC midnight
   */
  private dateToDateOnlyString(date: Date): string {
    const pad = (n: number) => n.toString().padStart(2, '0')
    const year = date.getUTCFullYear()
    const month = pad(date.getUTCMonth() + 1)
    const day = pad(date.getUTCDate())
    return `${year}-${month}-${day}`
  }

  /**
   * Convert Date to ISO string preserving local time components
   * Unlike toISOString() which converts to UTC, this preserves the browser's local time
   */
  private dateToLocalISOString(date: Date): string {
    const pad = (n: number) => n.toString().padStart(2, '0')
    const year = date.getFullYear()
    const month = pad(date.getMonth() + 1)
    const day = pad(date.getDate())
    const hours = pad(date.getHours())
    const minutes = pad(date.getMinutes())
    const seconds = pad(date.getSeconds())
    const ms = date.getMilliseconds().toString().padStart(3, '0')

    return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}.${ms}`
  }

  /**
   * Convert CalDAV calendars to EventCalendar resources
   */
  public toEventCalendarResources(calendars: CalDavCalendar[]): EventCalendarResource[] {
    return calendars.map((cal) => ({
      id: cal.url,
      title: cal.displayName || 'Unnamed Calendar',
      eventBackgroundColor: cal.color,
      extendedProps: {
        description: cal.description,
        timezone: cal.timezone,
        ctag: cal.ctag,
        syncToken: cal.syncToken,
        components: cal.components,
      },
    }))
  }

  // ============================================================================
  // EventCalendar -> CalDAV Conversions
  // ============================================================================

  /**
   * Convert EventCalendar event to IcsEvent
   */
  public toIcsEvent(
    ecEvent: EventCalendarEvent | EventCalendarEventInput,
    options?: EventCalendarToCalDavOptions
  ): IcsEvent {
    const opts = options ?? {}
    const extProps = (ecEvent.extendedProps ?? {}) as Partial<CalDavExtendedProps>

    // Get or generate UID
    const uid = extProps.uid ?? opts.uidGenerator?.() ?? crypto.randomUUID()

    // Convert dates
    // For all-day events, parse date strings carefully to avoid timezone issues
    const parseDate = (dateValue: Date | string, isAllDay: boolean): Date => {
      if (dateValue instanceof Date) {
        return dateValue
      }

      // If all-day and string format is YYYY-MM-DD, parse components directly as UTC
      // All-day events in ICS are stored as UTC midnight
      if (isAllDay && typeof dateValue === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(dateValue)) {
        const [year, month, day] = dateValue.split('-').map(Number)
        const result = new Date(Date.UTC(year, month - 1, day))
        console.log('[EventCalendarAdapter] Parsing all-day date:', dateValue, '→', result)
        return result
      }

      return new Date(dateValue)
    }

    const isAllDay = ecEvent.allDay ?? false
    console.log('[EventCalendarAdapter] toIcsEvent - allDay:', isAllDay, 'start:', ecEvent.start, 'end:', ecEvent.end)

    const startDate = parseDate(ecEvent.start, isAllDay)
    const endDate = ecEvent.end
      ? parseDate(ecEvent.end, isAllDay)
      : startDate

    console.log('[EventCalendarAdapter] Parsed dates - start:', startDate, 'end:', endDate)

    // Determine timezone
    const timezone = extProps.timezone ?? opts.defaultTimezone

    // If event has extProps.timezone, it came from the server and dates are already "fake UTC"
    const isFakeUtc = !!extProps.timezone

    // Build IcsEvent
    // Note: EventCalendar already uses exclusive end dates for all-day events
    const icsEvent: IcsEvent = {
      uid,
      stamp: { date: new Date() },
      start: this.jsDateToIcsDate(startDate, isAllDay, timezone, isFakeUtc),
      end: this.jsDateToIcsDate(endDate, isAllDay, timezone, isFakeUtc),
      summary: typeof ecEvent.title === 'string' ? ecEvent.title : '',
      sequence: (extProps.sequence ?? 0) + 1,
    }

    // Add optional properties from extended props
    if (extProps.location) icsEvent.location = extProps.location
    if (extProps.description) icsEvent.description = extProps.description
    if (extProps.status && this.isValidStatus(extProps.status)) {
      icsEvent.status = extProps.status
    }
    if (extProps.categories) icsEvent.categories = extProps.categories
    if (extProps.priority != null) icsEvent.priority = String(extProps.priority)
    if (extProps.url) icsEvent.url = extProps.url
    if (extProps.created) icsEvent.created = this.jsDateToIcsDate(extProps.created, false, timezone, isFakeUtc)
    if (extProps.recurrenceRule) icsEvent.recurrenceRule = extProps.recurrenceRule

    // Convert recurrence ID for recurring instances
    if (extProps.recurrenceId) {
      icsEvent.recurrenceId = {
        value: this.jsDateToIcsDate(extProps.recurrenceId, ecEvent.allDay ?? false, timezone, isFakeUtc),
      }
    }

    // Convert organizer
    if (extProps.organizer) {
      const organizer: IcsOrganizer = {
        email: extProps.organizer.email,
      }
      if (extProps.organizer.displayName) {
        organizer.name = extProps.organizer.displayName
      }
      icsEvent.organizer = organizer
    }

    // Convert attendees
    if (extProps.attendees && extProps.attendees.length > 0) {
      icsEvent.attendees = extProps.attendees.map((att): IcsAttendee => ({
        email: att.email,
        name: att.displayName,
        role: att.role,
        partstat: (att.status as IcsAttendee['partstat']) ?? 'NEEDS-ACTION',
        rsvp: att.rsvp,
      }))
    }

    return icsEvent
  }

  /**
   * Check if a status string is a valid ICS event status
   */
  private isValidStatus(status: string): status is 'TENTATIVE' | 'CONFIRMED' | 'CANCELLED' {
    return ['TENTATIVE', 'CONFIRMED', 'CANCELLED'].includes(status)
  }

  /**
   * Convert EventCalendar event to a full IcsCalendar object
   */
  public toIcsCalendar(
    ecEvent: EventCalendarEvent | EventCalendarEventInput,
    options?: EventCalendarToCalDavOptions
  ): IcsCalendar {
    const icsEvent = this.toIcsEvent(ecEvent, options)

    return {
      prodId: '-//EventCalendarAdapter//NONSGML v1.0//EN',
      version: '2.0',
      events: [icsEvent],
    }
  }

  /**
   * Get the calendar URL from an EventCalendar event
   */
  public getCalendarUrl(ecEvent: EventCalendarEvent, defaultCalendarUrl?: string): string | undefined {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return extProps?.calendarUrl ?? defaultCalendarUrl
  }

  /**
   * Get the event URL from an EventCalendar event
   */
  public getEventUrl(ecEvent: EventCalendarEvent): string | undefined {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return extProps?.eventUrl
  }

  /**
   * Get the ETag from an EventCalendar event
   */
  public getEtag(ecEvent: EventCalendarEvent): string | undefined {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return extProps?.etag
  }

  /**
   * Check if an EventCalendar event is a recurring instance
   */
  public isRecurringInstance(ecEvent: EventCalendarEvent): boolean {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return extProps?.isRecurringInstance ?? false
  }

  /**
   * Check if an EventCalendar event has recurrence rule
   */
  public hasRecurrenceRule(ecEvent: EventCalendarEvent): boolean {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return !!extProps?.recurrenceRule
  }

  // ============================================================================
  // Duration Conversions
  // ============================================================================

  /**
   * Convert EventCalendar duration to seconds
   */
  public durationToSeconds(duration: EventCalendarDuration): number {
    let seconds = 0
    if (duration.years) seconds += duration.years * 365.25 * 24 * 60 * 60
    if (duration.months) seconds += duration.months * 30.44 * 24 * 60 * 60
    if (duration.weeks) seconds += duration.weeks * 7 * 24 * 60 * 60
    if (duration.days) seconds += duration.days * 24 * 60 * 60
    if (duration.hours) seconds += duration.hours * 60 * 60
    if (duration.minutes) seconds += duration.minutes * 60
    if (duration.seconds) seconds += duration.seconds
    return Math.round(seconds)
  }

  /**
   * Convert seconds to EventCalendar duration
   */
  public secondsToDuration(totalSeconds: number): EventCalendarDuration {
    const days = Math.floor(totalSeconds / (24 * 60 * 60))
    const remainingAfterDays = totalSeconds % (24 * 60 * 60)
    const hours = Math.floor(remainingAfterDays / (60 * 60))
    const remainingAfterHours = remainingAfterDays % (60 * 60)
    const minutes = Math.floor(remainingAfterHours / 60)
    const seconds = remainingAfterHours % 60

    const duration: EventCalendarDuration = {}
    if (days) duration.days = days
    if (hours) duration.hours = hours
    if (minutes) duration.minutes = minutes
    if (seconds) duration.seconds = seconds

    return duration
  }

  /**
   * Calculate duration between two EventCalendar events (for drop/resize delta)
   */
  public calculateDelta(
    oldEvent: EventCalendarEvent,
    newEvent: EventCalendarEvent
  ): { startDelta: EventCalendarDuration; endDelta: EventCalendarDuration } {
    const oldStart = oldEvent.start instanceof Date ? oldEvent.start : new Date(oldEvent.start)
    const newStart = newEvent.start instanceof Date ? newEvent.start : new Date(newEvent.start)
    const oldEnd = oldEvent.end instanceof Date ? oldEvent.end : new Date(oldEvent.end ?? oldStart)
    const newEnd = newEvent.end instanceof Date ? newEvent.end : new Date(newEvent.end ?? newStart)

    const startDeltaMs = newStart.getTime() - oldStart.getTime()
    const endDeltaMs = newEnd.getTime() - oldEnd.getTime()

    return {
      startDelta: this.secondsToDuration(Math.round(startDeltaMs / 1000)),
      endDelta: this.secondsToDuration(Math.round(endDeltaMs / 1000)),
    }
  }

  // ============================================================================
  // Attendee/Organizer Helpers
  // ============================================================================

  /**
   * Get attendees from an EventCalendar event
   */
  public getAttendees(ecEvent: EventCalendarEvent): ExtendedAttendee[] {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return extProps?.attendees ?? []
  }

  /**
   * Get organizer from an EventCalendar event
   */
  public getOrganizer(ecEvent: EventCalendarEvent): ExtendedOrganizer | undefined {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return extProps?.organizer
  }

  /**
   * Set attendees on an EventCalendar event (returns new event)
   */
  public setAttendees(
    ecEvent: EventCalendarEvent,
    attendees: ExtendedAttendee[]
  ): EventCalendarEvent {
    return {
      ...ecEvent,
      extendedProps: {
        ...(ecEvent.extendedProps ?? {}),
        attendees,
      },
    }
  }

  /**
   * Set organizer on an EventCalendar event (returns new event)
   */
  public setOrganizer(
    ecEvent: EventCalendarEvent,
    organizer: ExtendedOrganizer
  ): EventCalendarEvent {
    return {
      ...ecEvent,
      extendedProps: {
        ...(ecEvent.extendedProps ?? {}),
        organizer,
      },
    }
  }

  // ============================================================================
  // Event Property Helpers
  // ============================================================================

  /**
   * Get location from an EventCalendar event
   */
  public getLocation(ecEvent: EventCalendarEvent): string | undefined {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return extProps?.location
  }

  /**
   * Get description from an EventCalendar event
   */
  public getDescription(ecEvent: EventCalendarEvent): string | undefined {
    const extProps = ecEvent.extendedProps as Partial<CalDavExtendedProps> | undefined
    return extProps?.description
  }

  /**
   * Set location on an EventCalendar event (returns new event)
   */
  public setLocation(ecEvent: EventCalendarEvent, location: string): EventCalendarEvent {
    return {
      ...ecEvent,
      extendedProps: {
        ...(ecEvent.extendedProps ?? {}),
        location,
      },
    }
  }

  /**
   * Set description on an EventCalendar event (returns new event)
   */
  public setDescription(ecEvent: EventCalendarEvent, description: string): EventCalendarEvent {
    return {
      ...ecEvent,
      extendedProps: {
        ...(ecEvent.extendedProps ?? {}),
        description,
      },
    }
  }

  // ============================================================================
  // Color Helpers
  // ============================================================================

  /**
   * Create a color map from calendars
   */
  public createCalendarColorMap(calendars: CalDavCalendar[]): Map<string, string> {
    const colorMap = new Map<string, string>()
    for (const cal of calendars) {
      if (cal.color) {
        colorMap.set(cal.url, cal.color)
      }
    }
    return colorMap
  }

  /**
   * Apply calendar colors to events
   */
  public applyCalendarColors(
    events: EventCalendarEvent[],
    calendarColors: Map<string, string>
  ): EventCalendarEvent[] {
    return events.map((event) => {
      const calendarUrl = this.getCalendarUrl(event)
      if (calendarUrl && calendarColors.has(calendarUrl)) {
        return {
          ...event,
          backgroundColor: calendarColors.get(calendarUrl),
        }
      }
      return event
    })
  }

  // ============================================================================
  // Private Helper Methods
  // ============================================================================

  /**
   * Deduplicate attendees by email, keeping the one with the most "advanced" status.
   *
   * This fixes a SabreDAV bug where REPLY processing can add duplicate attendees
   * instead of updating the existing one (due to email case sensitivity or format differences).
   *
   * Status priority (most to least advanced): ACCEPTED > TENTATIVE > DECLINED > NEEDS-ACTION
   */
  private deduplicateAttendees(attendees?: ExtendedAttendee[]): ExtendedAttendee[] | undefined {
    if (!attendees || attendees.length === 0) {
      return attendees
    }

    // Status priority map (higher = more definitive response)
    const statusPriority: Record<string, number> = {
      'ACCEPTED': 4,
      'TENTATIVE': 3,
      'DECLINED': 2,
      'NEEDS-ACTION': 1,
    }

    const getStatusPriority = (status?: string): number => {
      return statusPriority[status ?? 'NEEDS-ACTION'] ?? 0
    }

    // Group by normalized email (lowercase)
    const byEmail = new Map<string, ExtendedAttendee>()

    for (const attendee of attendees) {
      const normalizedEmail = attendee.email.toLowerCase().trim()
      const existing = byEmail.get(normalizedEmail)

      if (!existing) {
        // First occurrence of this email
        byEmail.set(normalizedEmail, attendee)
      } else {
        // Duplicate found - keep the one with higher status priority
        const existingPriority = getStatusPriority(existing.status)
        const newPriority = getStatusPriority(attendee.status)

        if (newPriority > existingPriority) {
          // New attendee has more definitive status - replace
          byEmail.set(normalizedEmail, attendee)
        } else if (newPriority === existingPriority && attendee.displayName && !existing.displayName) {
          // Same status but new one has display name - prefer it
          byEmail.set(normalizedEmail, attendee)
        }
        // Otherwise keep existing
      }
    }

    return Array.from(byEmail.values())
  }

  /**
   * Generate a unique event ID from IcsEvent
   */
  private generateEventId(icsEvent: IcsEvent): string {
    if (icsEvent.recurrenceId) {
      return `${icsEvent.uid}_${icsEvent.recurrenceId.value.date.getTime()}`
    }
    return icsEvent.uid
  }

  /**
   * Convert IcsDateObject to JavaScript Date
   */
  private icsDateToJsDate(icsDate: IcsDateObject): Date {
    // Use local date if available, otherwise use UTC date
    if (icsDate.local?.date) {
      return icsDate.local.date
    }
    return icsDate.date
  }

  /**
   * Convert JavaScript Date to IcsDateObject
   *
   * IMPORTANT: EventCalendar returns dates in browser local time.
   * ts-ics uses date.getUTCHours() etc. to generate ICS, so we need to
   * create a "fake UTC" date where UTC components match the local time we want.
   *
   * Example: User in Paris (UTC+1) drags event to 15:00 local
   * - Input date: Date representing 15:00 local (14:00 UTC internally)
   * - We want ICS: DTSTART:20260121T150000Z or DTSTART;TZID=Europe/Paris:20260121T150000
   * - Solution: Create date where getUTCHours() = 15
   *
   * @param date - The date to convert
   * @param allDay - Whether this is an all-day event
   * @param timezone - The timezone to use
   * @param isFakeUtc - If true, date is already "fake UTC" (use getUTC* methods)
   */
  private jsDateToIcsDate(date: Date, allDay: boolean, timezone?: string, isFakeUtc = false): IcsDateObject {
    if (allDay) {
      // For all-day events, use DATE type (no time component)
      // Create a UTC date with the local date components
      const utcDate = new Date(Date.UTC(
        isFakeUtc ? date.getUTCFullYear() : date.getFullYear(),
        isFakeUtc ? date.getUTCMonth() : date.getMonth(),
        isFakeUtc ? date.getUTCDate() : date.getDate()
      ))
      return {
        type: 'DATE',
        date: utcDate,
      }
    }

    // For timed events, create a "fake UTC" date where UTC components = local components
    // This ensures ts-ics generates the correct time in the ICS output
    const fakeUtcDate = isFakeUtc
      ? date  // Already fake UTC, use as-is
      : new Date(Date.UTC(
          date.getFullYear(),
          date.getMonth(),
          date.getDate(),
          date.getHours(),
          date.getMinutes(),
          date.getSeconds()
        ))

    const tz = timezone || Intl.DateTimeFormat().resolvedOptions().timeZone
    const tzOffset = this.getTimezoneOffset(isFakeUtc ? date : new Date(
      date.getFullYear(),
      date.getMonth(),
      date.getDate(),
      date.getHours(),
      date.getMinutes()
    ), tz)

    return {
      type: 'DATE-TIME',
      date: fakeUtcDate,
      local: {
        date: fakeUtcDate,
        timezone: tz,
        tzoffset: tzOffset,
      },
    }
  }

  /**
   * Get timezone offset string for a date and timezone
   * Returns format like "+0200" or "-0500"
   */
  public getTimezoneOffset(date: Date, timezone: string): string {
    try {
      // Create formatter for the timezone
      const formatter = new Intl.DateTimeFormat('en-US', {
        timeZone: timezone,
        timeZoneName: 'longOffset',
      })
      const parts = formatter.formatToParts(date)
      const tzPart = parts.find((p) => p.type === 'timeZoneName')

      if (tzPart?.value) {
        // Convert "GMT+02:00" to "+0200"
        const match = tzPart.value.match(/GMT([+-])(\d{1,2}):?(\d{2})?/)
        if (match) {
          const sign = match[1]
          const hours = match[2].padStart(2, '0')
          const minutes = (match[3] || '00').padStart(2, '0')
          return `${sign}${hours}${minutes}`
        }
      }
      return '+0000'
    } catch {
      return '+0000'
    }
  }

  /**
   * Add ICS duration object to a date
   */
  private addIcsDurationToDate(date: Date, duration: IcsDuration): Date {
    const result = new Date(date)

    if (duration.weeks) result.setDate(result.getDate() + duration.weeks * 7)
    if (duration.days) result.setDate(result.getDate() + duration.days)
    if (duration.hours) result.setHours(result.getHours() + duration.hours)
    if (duration.minutes) result.setMinutes(result.getMinutes() + duration.minutes)
    if (duration.seconds) result.setSeconds(result.getSeconds() + duration.seconds)

    return result
  }

  /**
   * Add string duration to a date (ISO 8601 format)
   */
  private addDurationToDate(date: Date, duration: string): Date {
    // Parse ISO 8601 duration (P1D, PT1H, etc.)
    const result = new Date(date)

    const regex = /P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?/
    const match = duration.match(regex)

    if (!match) return result

    const [, years, months, weeks, days, hours, minutes, seconds] = match

    if (years) result.setFullYear(result.getFullYear() + parseInt(years))
    if (months) result.setMonth(result.getMonth() + parseInt(months))
    if (weeks) result.setDate(result.getDate() + parseInt(weeks) * 7)
    if (days) result.setDate(result.getDate() + parseInt(days))
    if (hours) result.setHours(result.getHours() + parseInt(hours))
    if (minutes) result.setMinutes(result.getMinutes() + parseInt(minutes))
    if (seconds) result.setSeconds(result.getSeconds() + parseInt(seconds))

    return result
  }
}

// ============================================================================
// Factory & Singleton
// ============================================================================

let _adapterInstance: EventCalendarAdapter | null = null

/**
 * Get or create a singleton adapter instance
 */
export function getEventCalendarAdapter(): EventCalendarAdapter {
  if (!_adapterInstance) {
    _adapterInstance = new EventCalendarAdapter()
  }
  return _adapterInstance
}

/**
 * Create a new adapter instance
 */
export function createEventCalendarAdapter(): EventCalendarAdapter {
  return new EventCalendarAdapter()
}

// ============================================================================
// Standalone Helper Functions
// ============================================================================

/**
 * Quick conversion from CalDAV events to EventCalendar format
 */
export function caldavToEventCalendar(
  caldavEvents: CalDavEvent[],
  options?: CalDavToEventCalendarOptions
): EventCalendarEvent[] {
  return getEventCalendarAdapter().toEventCalendarEvents(caldavEvents, options)
}

/**
 * Quick conversion from EventCalendar event to IcsEvent
 */
export function eventCalendarToIcs(
  ecEvent: EventCalendarEvent | EventCalendarEventInput,
  options?: EventCalendarToCalDavOptions
): IcsEvent {
  return getEventCalendarAdapter().toIcsEvent(ecEvent, options)
}

/**
 * Quick conversion from EventCalendar event to IcsCalendar
 */
export function eventCalendarToIcsCalendar(
  ecEvent: EventCalendarEvent | EventCalendarEventInput,
  options?: EventCalendarToCalDavOptions
): IcsCalendar {
  return getEventCalendarAdapter().toIcsCalendar(ecEvent, options)
}

/**
 * Quick conversion from CalDAV calendars to EventCalendar resources
 */
export function calendarsToResources(calendars: CalDavCalendar[]): EventCalendarResource[] {
  return getEventCalendarAdapter().toEventCalendarResources(calendars)
}
