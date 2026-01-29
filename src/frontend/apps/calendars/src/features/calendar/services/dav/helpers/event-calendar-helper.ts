/**
 * Event Calendar Helper Functions
 *
 * Utility functions for working with EventCalendar (vkurko/calendar) format.
 * These are standalone helpers that don't require the full adapter.
 *
 * @see https://github.com/vkurko/calendar
 */

import type { IcsEvent, IcsDateObject, IcsRecurrenceRule } from 'ts-ics'
import { getEventCalendarAdapter } from '../EventCalendarAdapter'
import type {
  EventCalendarEvent,
  EventCalendarEventInput,
  EventCalendarDuration,
  EventCalendarDurationInput,
  EventCalendarView,
  EventCalendarResource,
} from '../types/event-calendar'
import type { CalDavAttendee } from '../types/caldav-service'

// ============================================================================
// Date/Time Helpers
// ============================================================================

/**
 * Format a date for EventCalendar (ISO string or Date object)
 */
export function formatEventCalendarDate(date: Date | string): string {
  if (typeof date === 'string') return date
  return date.toISOString()
}

/**
 * Parse an EventCalendar date to a JavaScript Date
 */
export function parseEventCalendarDate(date: Date | string): Date {
  if (date instanceof Date) return date
  return new Date(date)
}

/**
 * Check if two dates are on the same day
 */
export function isSameDay(date1: Date | string, date2: Date | string): boolean {
  const d1 = parseEventCalendarDate(date1)
  const d2 = parseEventCalendarDate(date2)
  return (
    d1.getFullYear() === d2.getFullYear() &&
    d1.getMonth() === d2.getMonth() &&
    d1.getDate() === d2.getDate()
  )
}

/**
 * Get the start of day for a date
 */
export function startOfDay(date: Date | string): Date {
  const d = parseEventCalendarDate(date)
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0)
}

/**
 * Get the end of day for a date
 */
export function endOfDay(date: Date | string): Date {
  const d = parseEventCalendarDate(date)
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59, 999)
}

/**
 * Get the start of week for a date (configurable first day)
 */
export function startOfWeek(date: Date | string, firstDay: number = 1): Date {
  const d = parseEventCalendarDate(date)
  const day = d.getDay()
  const diff = (day < firstDay ? 7 : 0) + day - firstDay
  d.setDate(d.getDate() - diff)
  return startOfDay(d)
}

/**
 * Get the end of week for a date
 */
export function endOfWeek(date: Date | string, firstDay: number = 1): Date {
  const start = startOfWeek(date, firstDay)
  start.setDate(start.getDate() + 6)
  return endOfDay(start)
}

/**
 * Get the start of month for a date
 */
export function startOfMonth(date: Date | string): Date {
  const d = parseEventCalendarDate(date)
  return new Date(d.getFullYear(), d.getMonth(), 1, 0, 0, 0, 0)
}

/**
 * Get the end of month for a date
 */
export function endOfMonth(date: Date | string): Date {
  const d = parseEventCalendarDate(date)
  return new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59, 999)
}

// ============================================================================
// Duration Helpers
// ============================================================================

/**
 * Parse duration input to EventCalendarDuration
 */
export function parseDuration(input: EventCalendarDurationInput): EventCalendarDuration {
  if (typeof input === 'number') {
    // Input is total seconds
    return secondsToDuration(input)
  }

  if (typeof input === 'string') {
    // Input is 'hh:mm:ss' or 'hh:mm' format
    const parts = input.split(':').map(Number)
    if (parts.length === 2) {
      return { hours: parts[0], minutes: parts[1] }
    } else if (parts.length === 3) {
      return { hours: parts[0], minutes: parts[1], seconds: parts[2] }
    }
    return {}
  }

  // Input is already an object
  return input
}

/**
 * Convert duration to total seconds
 */
export function durationToSeconds(duration: EventCalendarDuration): number {
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
 * Convert seconds to duration object
 */
export function secondsToDuration(totalSeconds: number): EventCalendarDuration {
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
 * Format duration as 'hh:mm:ss' string
 */
export function formatDuration(duration: EventCalendarDuration): string {
  const totalSeconds = durationToSeconds(duration)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  const pad = (n: number) => n.toString().padStart(2, '0')

  if (seconds > 0) {
    return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
  }
  return `${pad(hours)}:${pad(minutes)}`
}

/**
 * Add duration to a date
 */
export function addDuration(date: Date | string, duration: EventCalendarDuration): Date {
  const result = new Date(parseEventCalendarDate(date))
  const seconds = durationToSeconds(duration)
  result.setTime(result.getTime() + seconds * 1000)
  return result
}

/**
 * Subtract duration from a date
 */
export function subtractDuration(date: Date | string, duration: EventCalendarDuration): Date {
  const result = new Date(parseEventCalendarDate(date))
  const seconds = durationToSeconds(duration)
  result.setTime(result.getTime() - seconds * 1000)
  return result
}

// ============================================================================
// Event Helpers
// ============================================================================

/**
 * Check if an event is an all-day event
 */
export function isAllDayEvent(event: EventCalendarEvent | EventCalendarEventInput): boolean {
  return event.allDay === true
}

/**
 * Check if an event spans multiple days
 */
export function isMultiDayEvent(event: EventCalendarEvent | EventCalendarEventInput): boolean {
  const start = parseEventCalendarDate(event.start)
  const end = event.end ? parseEventCalendarDate(event.end) : start
  return !isSameDay(start, end)
}

/**
 * Get the duration of an event in minutes
 */
export function getEventDurationMinutes(event: EventCalendarEvent | EventCalendarEventInput): number {
  const start = parseEventCalendarDate(event.start)
  const end = event.end ? parseEventCalendarDate(event.end) : start
  return Math.round((end.getTime() - start.getTime()) / (1000 * 60))
}

/**
 * Check if an event overlaps with a time range
 */
export function eventOverlapsRange(
  event: EventCalendarEvent | EventCalendarEventInput,
  rangeStart: Date | string,
  rangeEnd: Date | string
): boolean {
  const eventStart = parseEventCalendarDate(event.start)
  const eventEnd = event.end ? parseEventCalendarDate(event.end) : eventStart
  const start = parseEventCalendarDate(rangeStart)
  const end = parseEventCalendarDate(rangeEnd)

  return eventStart < end && eventEnd > start
}

/**
 * Filter events that overlap with a time range
 */
export function filterEventsInRange(
  events: EventCalendarEvent[],
  rangeStart: Date | string,
  rangeEnd: Date | string
): EventCalendarEvent[] {
  return events.filter((event) => eventOverlapsRange(event, rangeStart, rangeEnd))
}

/**
 * Sort events by start date
 */
export function sortEventsByStart(events: EventCalendarEvent[]): EventCalendarEvent[] {
  return [...events].sort((a, b) => {
    const aStart = parseEventCalendarDate(a.start)
    const bStart = parseEventCalendarDate(b.start)
    return aStart.getTime() - bStart.getTime()
  })
}

/**
 * Group events by date
 */
export function groupEventsByDate(events: EventCalendarEvent[]): Map<string, EventCalendarEvent[]> {
  const groups = new Map<string, EventCalendarEvent[]>()

  for (const event of events) {
    const dateKey = startOfDay(event.start).toISOString().split('T')[0]
    const existing = groups.get(dateKey) ?? []
    existing.push(event)
    groups.set(dateKey, existing)
  }

  return groups
}

/**
 * Create a new event with updated times
 */
export function moveEvent(
  event: EventCalendarEvent,
  newStart: Date | string,
  newEnd?: Date | string
): EventCalendarEvent {
  const start = parseEventCalendarDate(newStart)
  const originalStart = parseEventCalendarDate(event.start)
  const originalEnd = event.end ? parseEventCalendarDate(event.end) : originalStart

  // Calculate original duration
  const duration = originalEnd.getTime() - originalStart.getTime()

  // Calculate new end if not provided
  const end = newEnd ? parseEventCalendarDate(newEnd) : new Date(start.getTime() + duration)

  return {
    ...event,
    start,
    end,
  }
}

/**
 * Resize an event by changing its end time
 */
export function resizeEvent(
  event: EventCalendarEvent,
  newEnd: Date | string
): EventCalendarEvent {
  return {
    ...event,
    end: parseEventCalendarDate(newEnd),
  }
}

// ============================================================================
// View Helpers
// ============================================================================

/**
 * Get the date range for a view
 */
export function getViewDateRange(
  view: EventCalendarView,
  currentDate: Date | string
): { start: Date; end: Date } {
  const date = parseEventCalendarDate(currentDate)

  switch (view) {
    case 'dayGridDay':
    case 'timeGridDay':
    case 'listDay':
    case 'resourceTimeGridDay':
    case 'resourceTimelineDay':
      return { start: startOfDay(date), end: endOfDay(date) }

    case 'dayGridWeek':
    case 'timeGridWeek':
    case 'listWeek':
    case 'resourceTimeGridWeek':
    case 'resourceTimelineWeek':
      return { start: startOfWeek(date), end: endOfWeek(date) }

    case 'dayGridMonth':
    case 'listMonth':
    case 'resourceTimelineMonth':
      return { start: startOfMonth(date), end: endOfMonth(date) }

    case 'listYear':
      return {
        start: new Date(date.getFullYear(), 0, 1),
        end: new Date(date.getFullYear(), 11, 31, 23, 59, 59, 999),
      }

    default:
      return { start: startOfWeek(date), end: endOfWeek(date) }
  }
}

/**
 * Check if a view is a list view
 */
export function isListView(view: EventCalendarView): boolean {
  return view.startsWith('list')
}

/**
 * Check if a view is a resource view
 */
export function isResourceView(view: EventCalendarView): boolean {
  return view.startsWith('resource')
}

/**
 * Check if a view is a timeline view
 */
export function isTimelineView(view: EventCalendarView): boolean {
  return view.toLowerCase().includes('timeline')
}

// ============================================================================
// Resource Helpers
// ============================================================================

/**
 * Find a resource by ID
 */
export function findResourceById(
  resources: EventCalendarResource[],
  id: string | number
): EventCalendarResource | undefined {
  for (const resource of resources) {
    if (resource.id === id) return resource
    if (resource.children) {
      const found = findResourceById(resource.children, id)
      if (found) return found
    }
  }
  return undefined
}

/**
 * Flatten nested resources
 */
export function flattenResources(resources: EventCalendarResource[]): EventCalendarResource[] {
  const result: EventCalendarResource[] = []

  for (const resource of resources) {
    result.push(resource)
    if (resource.children) {
      result.push(...flattenResources(resource.children))
    }
  }

  return result
}

/**
 * Get events for a specific resource
 */
export function getEventsForResource(
  events: EventCalendarEvent[],
  resourceId: string | number
): EventCalendarEvent[] {
  return events.filter((event) => event.resourceIds?.includes(resourceId))
}

// ============================================================================
// ICS Conversion Helpers
// ============================================================================

/**
 * Convert IcsDateObject to JavaScript Date.
 *
 * Always returns icsDate.date (true UTC) so that downstream code using
 * getHours()/getMinutes() gets correct browser-local time automatically.
 */
export function icsDateToJsDate(icsDate: IcsDateObject): Date {
  return icsDate.date
}

/**
 * Convert JavaScript Date to IcsDateObject.
 *
 * Uses the adapter's Intl-based timezone conversion to produce correct
 * fake UTC dates (where getUTCHours() = local hours in the target timezone).
 */
export function jsDateToIcsDate(date: Date, allDay: boolean = false, timezone?: string): IcsDateObject {
  if (allDay) {
    const utcDate = new Date(Date.UTC(
      date.getFullYear(), date.getMonth(), date.getDate()
    ))
    return {
      type: 'DATE',
      date: utcDate,
    }
  }

  const adapter = getEventCalendarAdapter()
  const tz = timezone || Intl.DateTimeFormat().resolvedOptions().timeZone
  const components = adapter.getDateComponentsInTimezone(date, tz)
  const fakeUtcDate = new Date(Date.UTC(
    components.year, components.month - 1, components.day,
    components.hours, components.minutes, components.seconds
  ))
  const tzOffset = adapter.getTimezoneOffset(date, tz)

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
 * Check if an IcsEvent is an all-day event
 */
export function isIcsEventAllDay(event: IcsEvent): boolean {
  return event.start.type === 'DATE'
}

/**
 * Get the timezone from an IcsEvent
 */
export function getIcsEventTimezone(event: IcsEvent): string | undefined {
  return event.start.local?.timezone
}

// ============================================================================
// Recurrence Helpers
// ============================================================================

/**
 * Check if an event has a recurrence rule
 */
export function hasRecurrence(event: IcsEvent): boolean {
  return !!event.recurrenceRule
}

/**
 * Check if an event is a recurring instance (has recurrenceId)
 */
export function isRecurringInstance(event: IcsEvent): boolean {
  return !!event.recurrenceId
}

/**
 * Get a human-readable description of recurrence rule
 */
export function describeRecurrence(rule: IcsRecurrenceRule): string {
  const parts: string[] = []

  // Frequency
  const freqMap: Record<string, string> = {
    DAILY: 'day',
    WEEKLY: 'week',
    MONTHLY: 'month',
    YEARLY: 'year',
  }
  const freq = freqMap[rule.frequency] ?? rule.frequency.toLowerCase()

  // Interval
  const interval = rule.interval ?? 1
  if (interval === 1) {
    parts.push(`Every ${freq}`)
  } else {
    parts.push(`Every ${interval} ${freq}s`)
  }

  // Days of week
  if (rule.byDay && rule.byDay.length > 0) {
    const dayMap: Record<string, string> = {
      SU: 'Sunday',
      MO: 'Monday',
      TU: 'Tuesday',
      WE: 'Wednesday',
      TH: 'Thursday',
      FR: 'Friday',
      SA: 'Saturday',
    }
    const days = rule.byDay.map((d) => {
      const dayCode = typeof d === 'string' ? d : d.day
      return dayMap[dayCode] ?? dayCode
    })
    parts.push(`on ${days.join(', ')}`)
  }

  // Count
  if (rule.count) {
    parts.push(`${rule.count} times`)
  }

  // Until
  if (rule.until) {
    const untilDate = rule.until instanceof Date ? rule.until : new Date(rule.until.date)
    parts.push(`until ${untilDate.toLocaleDateString()}`)
  }

  return parts.join(' ')
}

// ============================================================================
// Color Helpers
// ============================================================================

/**
 * Generate a color from a string (for consistent calendar colors)
 */
export function stringToColor(str: string): string {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }

  const h = hash % 360
  return `hsl(${h}, 65%, 50%)`
}

/**
 * Check if a color is dark (for text contrast)
 */
export function isColorDark(color: string): boolean {
  // Convert hex to RGB
  let r: number, g: number, b: number

  if (color.startsWith('#')) {
    const hex = color.slice(1)
    if (hex.length === 3) {
      r = parseInt(hex[0] + hex[0], 16)
      g = parseInt(hex[1] + hex[1], 16)
      b = parseInt(hex[2] + hex[2], 16)
    } else {
      r = parseInt(hex.slice(0, 2), 16)
      g = parseInt(hex.slice(2, 4), 16)
      b = parseInt(hex.slice(4, 6), 16)
    }
  } else if (color.startsWith('rgb')) {
    const match = color.match(/\d+/g)
    if (!match) return false
    r = parseInt(match[0])
    g = parseInt(match[1])
    b = parseInt(match[2])
  } else {
    return false
  }

  // Calculate relative luminance
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return luminance < 0.5
}

/**
 * Get contrasting text color (black or white)
 */
export function getContrastingTextColor(backgroundColor: string): string {
  return isColorDark(backgroundColor) ? '#ffffff' : '#000000'
}

// ============================================================================
// Attendee Helpers
// ============================================================================

/**
 * Get display name for an attendee
 */
export function getAttendeeDisplayName(attendee: CalDavAttendee): string {
  return attendee.name ?? attendee.email
}

/**
 * Get status icon for an attendee
 */
export function getAttendeeStatusIcon(status?: CalDavAttendee['partstat']): string {
  switch (status) {
    case 'ACCEPTED':
      return '✓'
    case 'DECLINED':
      return '✗'
    case 'TENTATIVE':
      return '?'
    case 'NEEDS-ACTION':
    default:
      return '○'
  }
}

/**
 * Get status color for an attendee
 */
export function getAttendeeStatusColor(status?: CalDavAttendee['partstat']): string {
  switch (status) {
    case 'ACCEPTED':
      return '#22c55e' // green
    case 'DECLINED':
      return '#ef4444' // red
    case 'TENTATIVE':
      return '#f59e0b' // amber
    case 'NEEDS-ACTION':
    default:
      return '#6b7280' // gray
  }
}
