/**
 * Tests for Event Calendar Helper functions
 */
import {
  formatEventCalendarDate,
  parseEventCalendarDate,
  isSameDay,
  startOfDay,
  endOfDay,
  startOfWeek,
  endOfWeek,
  startOfMonth,
  endOfMonth,
  parseDuration,
  durationToSeconds,
  secondsToDuration,
  formatDuration,
  addDuration,
  subtractDuration,
  isAllDayEvent,
  isMultiDayEvent,
  getEventDurationMinutes,
  eventOverlapsRange,
  filterEventsInRange,
  sortEventsByStart,
  groupEventsByDate,
  moveEvent,
  resizeEvent,
  getViewDateRange,
  isListView,
  isResourceView,
  isTimelineView,
  findResourceById,
  flattenResources,
  getEventsForResource,
  icsDateToJsDate,
  jsDateToIcsDate,
  isIcsEventAllDay,
  getIcsEventTimezone,
  hasRecurrence,
  isRecurringInstance,
  describeRecurrence,
  stringToColor,
  isColorDark,
  getContrastingTextColor,
  getAttendeeDisplayName,
  getAttendeeStatusIcon,
  getAttendeeStatusColor,
} from '../helpers/event-calendar-helper'
import type { EventCalendarEvent, EventCalendarResource, EventCalendarDuration } from '../types/event-calendar'
import type { IcsDateObject, IcsEvent, IcsRecurrenceRule } from 'ts-ics'

describe('event-calendar-helper', () => {
  // ============================================================================
  // Date/Time Helpers
  // ============================================================================
  describe('Date/Time Helpers', () => {
    describe('formatEventCalendarDate', () => {
      it('returns ISO string for Date object', () => {
        const date = new Date('2025-01-15T10:30:00.000Z')
        const result = formatEventCalendarDate(date)
        expect(result).toBe('2025-01-15T10:30:00.000Z')
      })

      it('returns string as-is', () => {
        const dateStr = '2025-01-15T10:30:00.000Z'
        expect(formatEventCalendarDate(dateStr)).toBe(dateStr)
      })
    })

    describe('parseEventCalendarDate', () => {
      it('returns Date object for string input', () => {
        const result = parseEventCalendarDate('2025-01-15T10:30:00.000Z')
        expect(result instanceof Date).toBe(true)
        expect(result.toISOString()).toBe('2025-01-15T10:30:00.000Z')
      })

      it('returns same Date object for Date input', () => {
        const date = new Date('2025-01-15T10:30:00.000Z')
        expect(parseEventCalendarDate(date)).toBe(date)
      })
    })

    describe('isSameDay', () => {
      it('returns true for same day', () => {
        const date1 = new Date('2025-01-15T08:00:00.000Z')
        const date2 = new Date('2025-01-15T20:00:00.000Z')
        expect(isSameDay(date1, date2)).toBe(true)
      })

      it('returns false for different days', () => {
        // Using dates that are clearly different days in any timezone
        const date1 = new Date('2025-01-15T12:00:00.000Z')
        const date2 = new Date('2025-01-17T12:00:00.000Z')
        expect(isSameDay(date1, date2)).toBe(false)
      })
    })

    describe('startOfDay', () => {
      it('returns start of day', () => {
        const date = new Date('2025-01-15T14:30:45.123Z')
        const result = startOfDay(date)
        expect(result.getHours()).toBe(0)
        expect(result.getMinutes()).toBe(0)
        expect(result.getSeconds()).toBe(0)
        expect(result.getMilliseconds()).toBe(0)
      })
    })

    describe('endOfDay', () => {
      it('returns end of day', () => {
        const date = new Date('2025-01-15T14:30:45.123Z')
        const result = endOfDay(date)
        expect(result.getHours()).toBe(23)
        expect(result.getMinutes()).toBe(59)
        expect(result.getSeconds()).toBe(59)
        expect(result.getMilliseconds()).toBe(999)
      })
    })

    describe('startOfWeek', () => {
      it('returns Monday for firstDay=1 (default)', () => {
        const date = new Date(2025, 0, 15) // Wednesday
        const result = startOfWeek(date)
        expect(result.getDay()).toBe(1) // Monday
      })

      it('returns Sunday for firstDay=0', () => {
        const date = new Date(2025, 0, 15) // Wednesday
        const result = startOfWeek(date, 0)
        expect(result.getDay()).toBe(0) // Sunday
      })
    })

    describe('endOfWeek', () => {
      it('returns Sunday for firstDay=1 (Monday start)', () => {
        const date = new Date(2025, 0, 15) // Wednesday
        const result = endOfWeek(date)
        expect(result.getDay()).toBe(0) // Sunday
      })
    })

    describe('startOfMonth', () => {
      it('returns first day of month', () => {
        const date = new Date(2025, 0, 15)
        const result = startOfMonth(date)
        expect(result.getDate()).toBe(1)
        expect(result.getMonth()).toBe(0)
      })
    })

    describe('endOfMonth', () => {
      it('returns last day of month', () => {
        const date = new Date(2025, 0, 15) // January
        const result = endOfMonth(date)
        expect(result.getDate()).toBe(31)
        expect(result.getMonth()).toBe(0)
      })

      it('handles February in leap year', () => {
        const date = new Date(2024, 1, 15) // February 2024 (leap year)
        const result = endOfMonth(date)
        expect(result.getDate()).toBe(29)
      })
    })
  })

  // ============================================================================
  // Duration Helpers
  // ============================================================================
  describe('Duration Helpers', () => {
    describe('parseDuration', () => {
      it('parses number as total seconds', () => {
        const result = parseDuration(3665)
        expect(result.hours).toBe(1)
        expect(result.minutes).toBe(1)
        expect(result.seconds).toBe(5)
      })

      it('parses hh:mm string', () => {
        const result = parseDuration('02:30')
        expect(result.hours).toBe(2)
        expect(result.minutes).toBe(30)
      })

      it('parses hh:mm:ss string', () => {
        const result = parseDuration('01:30:45')
        expect(result.hours).toBe(1)
        expect(result.minutes).toBe(30)
        expect(result.seconds).toBe(45)
      })

      it('returns object as-is', () => {
        const duration = { hours: 1, minutes: 30 }
        expect(parseDuration(duration)).toBe(duration)
      })
    })

    describe('durationToSeconds', () => {
      it('converts duration to total seconds', () => {
        const duration: EventCalendarDuration = { hours: 1, minutes: 30, seconds: 15 }
        expect(durationToSeconds(duration)).toBe(5415)
      })

      it('handles days', () => {
        const duration: EventCalendarDuration = { days: 1, hours: 2 }
        expect(durationToSeconds(duration)).toBe(93600)
      })
    })

    describe('secondsToDuration', () => {
      it('converts seconds to duration object', () => {
        const result = secondsToDuration(5415)
        expect(result.hours).toBe(1)
        expect(result.minutes).toBe(30)
        expect(result.seconds).toBe(15)
      })

      it('includes days when appropriate', () => {
        const result = secondsToDuration(93600)
        expect(result.days).toBe(1)
        expect(result.hours).toBe(2)
      })
    })

    describe('formatDuration', () => {
      it('formats as hh:mm', () => {
        const duration: EventCalendarDuration = { hours: 2, minutes: 30 }
        expect(formatDuration(duration)).toBe('02:30')
      })

      it('formats as hh:mm:ss when seconds present', () => {
        const duration: EventCalendarDuration = { hours: 1, minutes: 5, seconds: 30 }
        expect(formatDuration(duration)).toBe('01:05:30')
      })
    })

    describe('addDuration', () => {
      it('adds duration to date', () => {
        const date = new Date('2025-01-15T10:00:00.000Z')
        const duration: EventCalendarDuration = { hours: 2, minutes: 30 }
        const result = addDuration(date, duration)
        expect(result.toISOString()).toBe('2025-01-15T12:30:00.000Z')
      })
    })

    describe('subtractDuration', () => {
      it('subtracts duration from date', () => {
        const date = new Date('2025-01-15T12:30:00.000Z')
        const duration: EventCalendarDuration = { hours: 2, minutes: 30 }
        const result = subtractDuration(date, duration)
        expect(result.toISOString()).toBe('2025-01-15T10:00:00.000Z')
      })
    })
  })

  // ============================================================================
  // Event Helpers
  // ============================================================================
  describe('Event Helpers', () => {
    describe('isAllDayEvent', () => {
      it('returns true when allDay is true', () => {
        const event = { id: '1', start: new Date(), allDay: true } as EventCalendarEvent
        expect(isAllDayEvent(event)).toBe(true)
      })

      it('returns false when allDay is false', () => {
        const event = { id: '1', start: new Date(), allDay: false } as EventCalendarEvent
        expect(isAllDayEvent(event)).toBe(false)
      })
    })

    describe('isMultiDayEvent', () => {
      it('returns false for same day event', () => {
        const event = {
          id: '1',
          start: new Date('2025-01-15T10:00:00.000Z'),
          end: new Date('2025-01-15T12:00:00.000Z'),
        } as EventCalendarEvent
        expect(isMultiDayEvent(event)).toBe(false)
      })

      it('returns true for multi-day event', () => {
        const event = {
          id: '1',
          start: new Date('2025-01-15T10:00:00.000Z'),
          end: new Date('2025-01-16T12:00:00.000Z'),
        } as EventCalendarEvent
        expect(isMultiDayEvent(event)).toBe(true)
      })
    })

    describe('getEventDurationMinutes', () => {
      it('calculates duration in minutes', () => {
        const event = {
          id: '1',
          start: new Date('2025-01-15T10:00:00.000Z'),
          end: new Date('2025-01-15T11:30:00.000Z'),
        } as EventCalendarEvent
        expect(getEventDurationMinutes(event)).toBe(90)
      })
    })

    describe('eventOverlapsRange', () => {
      it('returns true when event overlaps range', () => {
        const event = {
          id: '1',
          start: new Date('2025-01-15T10:00:00.000Z'),
          end: new Date('2025-01-15T12:00:00.000Z'),
        } as EventCalendarEvent
        const result = eventOverlapsRange(
          event,
          '2025-01-15T11:00:00.000Z',
          '2025-01-15T14:00:00.000Z'
        )
        expect(result).toBe(true)
      })

      it('returns false when event is before range', () => {
        const event = {
          id: '1',
          start: new Date('2025-01-15T08:00:00.000Z'),
          end: new Date('2025-01-15T09:00:00.000Z'),
        } as EventCalendarEvent
        const result = eventOverlapsRange(
          event,
          '2025-01-15T10:00:00.000Z',
          '2025-01-15T12:00:00.000Z'
        )
        expect(result).toBe(false)
      })
    })

    describe('filterEventsInRange', () => {
      it('filters events within range', () => {
        const events = [
          { id: '1', start: new Date('2025-01-15T10:00:00.000Z'), end: new Date('2025-01-15T11:00:00.000Z') },
          { id: '2', start: new Date('2025-01-14T10:00:00.000Z'), end: new Date('2025-01-14T11:00:00.000Z') },
          { id: '3', start: new Date('2025-01-15T14:00:00.000Z'), end: new Date('2025-01-15T15:00:00.000Z') },
        ] as EventCalendarEvent[]

        const result = filterEventsInRange(
          events,
          '2025-01-15T09:00:00.000Z',
          '2025-01-15T12:00:00.000Z'
        )
        expect(result).toHaveLength(1)
        expect(result[0].id).toBe('1')
      })
    })

    describe('sortEventsByStart', () => {
      it('sorts events by start date', () => {
        const events = [
          { id: '2', start: new Date('2025-01-15T14:00:00.000Z') },
          { id: '1', start: new Date('2025-01-15T10:00:00.000Z') },
          { id: '3', start: new Date('2025-01-15T12:00:00.000Z') },
        ] as EventCalendarEvent[]

        const result = sortEventsByStart(events)
        expect(result.map(e => e.id)).toEqual(['1', '3', '2'])
      })
    })

    describe('groupEventsByDate', () => {
      it('groups events by date', () => {
        const events = [
          { id: '1', start: new Date('2025-01-15T10:00:00.000Z') },
          { id: '2', start: new Date('2025-01-15T14:00:00.000Z') },
          { id: '3', start: new Date('2025-01-16T10:00:00.000Z') },
        ] as EventCalendarEvent[]

        const result = groupEventsByDate(events)
        expect(result.size).toBe(2)
      })
    })

    describe('moveEvent', () => {
      it('moves event preserving duration', () => {
        const event = {
          id: '1',
          start: new Date('2025-01-15T10:00:00.000Z'),
          end: new Date('2025-01-15T12:00:00.000Z'),
        } as EventCalendarEvent

        const result = moveEvent(event, '2025-01-16T14:00:00.000Z')
        expect((result.start as Date).toISOString()).toBe('2025-01-16T14:00:00.000Z')
        expect((result.end as Date).toISOString()).toBe('2025-01-16T16:00:00.000Z')
      })
    })

    describe('resizeEvent', () => {
      it('changes event end time', () => {
        const event = {
          id: '1',
          start: new Date('2025-01-15T10:00:00.000Z'),
          end: new Date('2025-01-15T12:00:00.000Z'),
        } as EventCalendarEvent

        const result = resizeEvent(event, '2025-01-15T14:00:00.000Z')
        expect((result.end as Date).toISOString()).toBe('2025-01-15T14:00:00.000Z')
      })
    })
  })

  // ============================================================================
  // View Helpers
  // ============================================================================
  describe('View Helpers', () => {
    describe('getViewDateRange', () => {
      it('returns day range for dayGridDay view', () => {
        const { start, end } = getViewDateRange('dayGridDay', '2025-01-15')
        expect(start.getDate()).toBe(15)
        expect(end.getDate()).toBe(15)
      })

      it('returns month range for dayGridMonth view', () => {
        const { start, end } = getViewDateRange('dayGridMonth', '2025-01-15')
        expect(start.getDate()).toBe(1)
        expect(end.getDate()).toBe(31)
      })
    })

    describe('isListView', () => {
      it('returns true for list views', () => {
        expect(isListView('listDay')).toBe(true)
        expect(isListView('listWeek')).toBe(true)
      })

      it('returns false for non-list views', () => {
        expect(isListView('dayGridMonth')).toBe(false)
      })
    })

    describe('isResourceView', () => {
      it('returns true for resource views', () => {
        expect(isResourceView('resourceTimeGridDay')).toBe(true)
      })

      it('returns false for non-resource views', () => {
        expect(isResourceView('dayGridMonth')).toBe(false)
      })
    })

    describe('isTimelineView', () => {
      it('returns true for timeline views', () => {
        expect(isTimelineView('resourceTimelineDay')).toBe(true)
      })

      it('returns false for non-timeline views', () => {
        expect(isTimelineView('dayGridMonth')).toBe(false)
      })
    })
  })

  // ============================================================================
  // Resource Helpers
  // ============================================================================
  describe('Resource Helpers', () => {
    describe('findResourceById', () => {
      it('finds resource at top level', () => {
        const resources: EventCalendarResource[] = [
          { id: '1', title: 'Room A' },
          { id: '2', title: 'Room B' },
        ]
        const result = findResourceById(resources, '2')
        expect(result?.title).toBe('Room B')
      })

      it('finds nested resource', () => {
        const resources: EventCalendarResource[] = [
          { id: '1', title: 'Building A', children: [
            { id: '1-1', title: 'Room 101' },
          ]},
        ]
        const result = findResourceById(resources, '1-1')
        expect(result?.title).toBe('Room 101')
      })
    })

    describe('flattenResources', () => {
      it('flattens nested resources', () => {
        const resources: EventCalendarResource[] = [
          { id: '1', title: 'Building A', children: [
            { id: '1-1', title: 'Room 101' },
            { id: '1-2', title: 'Room 102' },
          ]},
          { id: '2', title: 'Building B' },
        ]
        const result = flattenResources(resources)
        expect(result).toHaveLength(4)
      })
    })

    describe('getEventsForResource', () => {
      it('filters events by resource', () => {
        const events = [
          { id: '1', start: new Date(), resourceIds: ['room-1'] },
          { id: '2', start: new Date(), resourceIds: ['room-2'] },
          { id: '3', start: new Date(), resourceIds: ['room-1', 'room-2'] },
        ] as EventCalendarEvent[]

        const result = getEventsForResource(events, 'room-1')
        expect(result).toHaveLength(2)
        expect(result.map(e => e.id)).toEqual(['1', '3'])
      })
    })
  })

  // ============================================================================
  // ICS Conversion Helpers
  // ============================================================================
  describe('ICS Conversion Helpers', () => {
    describe('icsDateToJsDate', () => {
      it('returns local date when present', () => {
        const localDate = new Date('2025-01-15T11:00:00.000Z')
        const icsDate: IcsDateObject = {
          type: 'DATE-TIME',
          date: new Date('2025-01-15T10:00:00.000Z'),
          local: { date: localDate, timezone: 'Europe/Paris', tzoffset: '+0100' },
        }
        expect(icsDateToJsDate(icsDate)).toBe(localDate)
      })

      it('returns UTC date when no local', () => {
        const utcDate = new Date('2025-01-15T10:00:00.000Z')
        const icsDate: IcsDateObject = {
          type: 'DATE-TIME',
          date: utcDate,
        }
        expect(icsDateToJsDate(icsDate)).toBe(utcDate)
      })
    })

    describe('jsDateToIcsDate', () => {
      it('creates DATE type for all-day', () => {
        const date = new Date('2025-01-15T00:00:00.000Z')
        const result = jsDateToIcsDate(date, true)
        expect(result.type).toBe('DATE')
      })

      it('creates DATE-TIME type with timezone', () => {
        const date = new Date('2025-01-15T10:00:00.000Z')
        const result = jsDateToIcsDate(date, false, 'Europe/Paris')
        expect(result.type).toBe('DATE-TIME')
        expect(result.local?.timezone).toBe('Europe/Paris')
      })
    })

    describe('isIcsEventAllDay', () => {
      it('returns true for DATE type start', () => {
        const event = {
          uid: 'test',
          stamp: { date: new Date() },
          start: { type: 'DATE', date: new Date() },
        } as IcsEvent
        expect(isIcsEventAllDay(event)).toBe(true)
      })
    })

    describe('getIcsEventTimezone', () => {
      it('returns timezone from start local', () => {
        const event = {
          uid: 'test',
          stamp: { date: new Date() },
          start: {
            type: 'DATE-TIME',
            date: new Date(),
            local: { date: new Date(), timezone: 'Europe/Paris', tzoffset: '+0100' },
          },
        } as IcsEvent
        expect(getIcsEventTimezone(event)).toBe('Europe/Paris')
      })
    })
  })

  // ============================================================================
  // Recurrence Helpers
  // ============================================================================
  describe('Recurrence Helpers', () => {
    describe('hasRecurrence', () => {
      it('returns true when recurrenceRule exists', () => {
        const event = {
          uid: 'test',
          stamp: { date: new Date() },
          start: { type: 'DATE-TIME', date: new Date() },
          recurrenceRule: { frequency: 'DAILY' },
        } as IcsEvent
        expect(hasRecurrence(event)).toBe(true)
      })
    })

    describe('isRecurringInstance', () => {
      it('returns true when recurrenceId exists', () => {
        const event = {
          uid: 'test',
          stamp: { date: new Date() },
          start: { type: 'DATE-TIME', date: new Date() },
          recurrenceId: { value: { type: 'DATE-TIME', date: new Date() } },
        } as IcsEvent
        expect(isRecurringInstance(event)).toBe(true)
      })
    })

    describe('describeRecurrence', () => {
      it('describes daily recurrence', () => {
        const rule: IcsRecurrenceRule = { frequency: 'DAILY' }
        expect(describeRecurrence(rule)).toBe('Every day')
      })

      it('describes weekly with interval', () => {
        const rule: IcsRecurrenceRule = { frequency: 'WEEKLY', interval: 2 }
        expect(describeRecurrence(rule)).toBe('Every 2 weeks')
      })

      it('describes with count', () => {
        const rule: IcsRecurrenceRule = { frequency: 'DAILY', count: 5 }
        expect(describeRecurrence(rule)).toContain('5 times')
      })
    })
  })

  // ============================================================================
  // Color Helpers
  // ============================================================================
  describe('Color Helpers', () => {
    describe('stringToColor', () => {
      it('generates consistent color for same string', () => {
        const color1 = stringToColor('Calendar A')
        const color2 = stringToColor('Calendar A')
        expect(color1).toBe(color2)
      })

      it('generates different colors for different strings', () => {
        const color1 = stringToColor('Calendar A')
        const color2 = stringToColor('Calendar B')
        expect(color1).not.toBe(color2)
      })

      it('returns valid HSL color', () => {
        const color = stringToColor('Test')
        expect(color).toMatch(/^hsl\(\d+, 65%, 50%\)$/)
      })
    })

    describe('isColorDark', () => {
      it('returns true for dark hex colors', () => {
        expect(isColorDark('#000000')).toBe(true)
        expect(isColorDark('#333333')).toBe(true)
      })

      it('returns false for light hex colors', () => {
        expect(isColorDark('#ffffff')).toBe(false)
        expect(isColorDark('#eeeeee')).toBe(false)
      })

      it('handles short hex format', () => {
        expect(isColorDark('#000')).toBe(true)
        expect(isColorDark('#fff')).toBe(false)
      })

      it('handles rgb format', () => {
        expect(isColorDark('rgb(0, 0, 0)')).toBe(true)
        expect(isColorDark('rgb(255, 255, 255)')).toBe(false)
      })
    })

    describe('getContrastingTextColor', () => {
      it('returns white for dark backgrounds', () => {
        expect(getContrastingTextColor('#000000')).toBe('#ffffff')
      })

      it('returns black for light backgrounds', () => {
        expect(getContrastingTextColor('#ffffff')).toBe('#000000')
      })
    })
  })

  // ============================================================================
  // Attendee Helpers
  // ============================================================================
  describe('Attendee Helpers', () => {
    describe('getAttendeeDisplayName', () => {
      it('returns name when present', () => {
        expect(getAttendeeDisplayName({ name: 'John Doe', email: 'john@example.com' })).toBe('John Doe')
      })

      it('returns email when no name', () => {
        expect(getAttendeeDisplayName({ email: 'john@example.com' })).toBe('john@example.com')
      })
    })

    describe('getAttendeeStatusIcon', () => {
      it('returns correct icons', () => {
        expect(getAttendeeStatusIcon('ACCEPTED')).toBe('✓')
        expect(getAttendeeStatusIcon('DECLINED')).toBe('✗')
        expect(getAttendeeStatusIcon('TENTATIVE')).toBe('?')
        expect(getAttendeeStatusIcon('NEEDS-ACTION')).toBe('○')
      })
    })

    describe('getAttendeeStatusColor', () => {
      it('returns correct colors', () => {
        expect(getAttendeeStatusColor('ACCEPTED')).toBe('#22c55e')
        expect(getAttendeeStatusColor('DECLINED')).toBe('#ef4444')
        expect(getAttendeeStatusColor('TENTATIVE')).toBe('#f59e0b')
      })
    })
  })
})
