/**
 * Tests for timezone conversion utilities.
 *
 * All tests use explicit UTC dates (new Date("...Z")) and assert on
 * getUTCHours()/getUTCMinutes() for fake UTC values, ensuring deterministic
 * results regardless of the CI machine's timezone.
 */
import { EventCalendarAdapter } from '../EventCalendarAdapter'
import { icsDateToJsDate } from '../helpers/event-calendar-helper'
import type { IcsDateObject } from 'ts-ics'

const adapter = new EventCalendarAdapter()

// ============================================================================
// 4. getDateComponentsInTimezone
// ============================================================================
describe('getDateComponentsInTimezone', () => {
  // 4.1 Europe/Paris winter (CET, UTC+1)
  it('converts UTC to Europe/Paris winter time (CET, UTC+1)', () => {
    const date = new Date('2026-01-29T14:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Europe/Paris')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 29, hours: 15, minutes: 0, seconds: 0 })
  })

  // 4.2 Europe/Paris summer (CEST, UTC+2)
  it('converts UTC to Europe/Paris summer time (CEST, UTC+2)', () => {
    const date = new Date('2026-07-15T13:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Europe/Paris')
    expect(result).toMatchObject({ year: 2026, month: 7, day: 15, hours: 15, minutes: 0, seconds: 0 })
  })

  // 4.3 America/New_York winter (EST, UTC-5)
  it('converts UTC to America/New_York winter time (EST, UTC-5)', () => {
    const date = new Date('2026-01-29T15:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'America/New_York')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 29, hours: 10, minutes: 0, seconds: 0 })
  })

  // 4.4 America/New_York summer (EDT, UTC-4)
  it('converts UTC to America/New_York summer time (EDT, UTC-4)', () => {
    const date = new Date('2026-07-15T14:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'America/New_York')
    expect(result).toMatchObject({ year: 2026, month: 7, day: 15, hours: 10, minutes: 0, seconds: 0 })
  })

  // 4.5 Asia/Tokyo (JST, UTC+9, no DST)
  it('converts UTC to Asia/Tokyo (JST, UTC+9, no DST)', () => {
    const date = new Date('2026-01-29T06:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Asia/Tokyo')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 29, hours: 15, minutes: 0, seconds: 0 })
  })

  // 4.6 UTC
  it('returns same components for UTC timezone', () => {
    const date = new Date('2026-01-29T15:30:45Z')
    const result = adapter.getDateComponentsInTimezone(date, 'UTC')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 29, hours: 15, minutes: 30, seconds: 45 })
  })

  // 4.7 Day change forward (UTC late → next day in ahead timezone)
  it('handles day change forward (UTC 23:00 → next day in Asia/Tokyo)', () => {
    const date = new Date('2026-01-29T23:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Asia/Tokyo')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 30, hours: 8, minutes: 0, seconds: 0 })
  })

  // 4.8 Day change backward (UTC early → previous day in behind timezone)
  it('handles day change backward (UTC 03:00 → previous day in America/New_York)', () => {
    const date = new Date('2026-01-29T03:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'America/New_York')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 28, hours: 22, minutes: 0, seconds: 0 })
  })

  // 4.9 Year change
  it('handles year change (Jan 1 UTC midnight → Dec 31 in America/Los_Angeles)', () => {
    const date = new Date('2026-01-01T00:30:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'America/Los_Angeles')
    expect(result).toMatchObject({ year: 2025, month: 12, day: 31, hours: 16, minutes: 30, seconds: 0 })
  })

  // 4.10 Half-hour offset (India, UTC+5:30)
  it('handles half-hour offset (Asia/Kolkata, UTC+5:30)', () => {
    const date = new Date('2026-01-29T10:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Asia/Kolkata')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 29, hours: 15, minutes: 30, seconds: 0 })
  })

  // 4.11 45-minute offset (Nepal, UTC+5:45)
  it('handles 45-minute offset (Asia/Kathmandu, UTC+5:45)', () => {
    const date = new Date('2026-01-29T10:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Asia/Kathmandu')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 29, hours: 15, minutes: 45, seconds: 0 })
  })

  // 4.12 DST transition CET→CEST (last Sunday of March 2026 = March 29)
  it('handles DST transition CET→CEST (before transition)', () => {
    // March 29 2026 at 00:30 UTC → 01:30 CET (still winter time)
    const date = new Date('2026-03-29T00:30:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Europe/Paris')
    expect(result.hours).toBe(1)
    expect(result.minutes).toBe(30)
  })

  it('handles DST transition CET→CEST (after transition)', () => {
    // March 29 2026 at 02:00 UTC → 04:00 CEST (summer time, clocks jumped 2→3)
    const date = new Date('2026-03-29T02:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Europe/Paris')
    expect(result.hours).toBe(4)
    expect(result.minutes).toBe(0)
  })

  // 4.13 DST transition CEST→CET (last Sunday of October 2026 = October 25)
  it('handles DST transition CEST→CET (before transition)', () => {
    // October 25 2026 at 00:00 UTC → 02:00 CEST (still summer time)
    const date = new Date('2026-10-25T00:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Europe/Paris')
    expect(result.hours).toBe(2)
    expect(result.minutes).toBe(0)
  })

  it('handles DST transition CEST→CET (after transition)', () => {
    // October 25 2026 at 02:00 UTC → 02:00 CET (winter time, clocks fell back)
    // At 01:00 UTC, clocks go from 03:00 CEST back to 02:00 CET
    // So at 02:00 UTC, it's 03:00 CET
    const date = new Date('2026-10-25T02:00:00Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Europe/Paris')
    expect(result.hours).toBe(3)
    expect(result.minutes).toBe(0)
  })

  // 4.14 Non-zero minutes and seconds
  it('preserves non-zero minutes and seconds', () => {
    const date = new Date('2026-01-29T14:37:42Z')
    const result = adapter.getDateComponentsInTimezone(date, 'Europe/Paris')
    expect(result).toMatchObject({ year: 2026, month: 1, day: 29, hours: 15, minutes: 37, seconds: 42 })
  })
})

// ============================================================================
// 5. icsDateToJsDate (bug fix)
// ============================================================================
describe('icsDateToJsDate', () => {
  // 5.1 Returns true UTC when local is present
  it('returns icsDate.date (true UTC) when local is present, not local.date', () => {
    const utcDate = new Date('2026-01-29T14:00:00.000Z')
    const fakeUtcDate = new Date('2026-01-29T15:00:00.000Z')
    const icsDate: IcsDateObject = {
      type: 'DATE-TIME',
      date: utcDate,
      local: { date: fakeUtcDate, timezone: 'Europe/Paris', tzoffset: '+0100' },
    }
    const result = icsDateToJsDate(icsDate)
    expect(result).toBe(utcDate)
    expect(result).not.toBe(fakeUtcDate)
    expect(result.getUTCHours()).toBe(14)
  })

  // 5.2 Returns date when local is absent (UTC pure events)
  it('returns icsDate.date when local is absent', () => {
    const utcDate = new Date('2026-01-29T14:00:00.000Z')
    const icsDate: IcsDateObject = {
      type: 'DATE-TIME',
      date: utcDate,
    }
    expect(icsDateToJsDate(icsDate)).toBe(utcDate)
  })

  // 5.3 Returns date for all-day events (DATE type)
  it('returns icsDate.date for all-day events (DATE type)', () => {
    const utcDate = new Date('2026-01-29T00:00:00.000Z')
    const icsDate: IcsDateObject = {
      type: 'DATE',
      date: utcDate,
    }
    const result = icsDateToJsDate(icsDate)
    expect(result).toBe(utcDate)
    expect(result.getUTCDate()).toBe(29)
  })
})

// ============================================================================
// 6. jsDateToIcsDate (timezone conversion)
// ============================================================================
describe('jsDateToIcsDate', () => {
  // Access private method via adapter for testing
  // We use toIcsEvent indirectly, but for unit tests we test via a
  // minimal EventCalendar event round-trip through the adapter.
  // Instead, we directly test the public-facing behavior through toIcsEvent.

  const makeEcEvent = (start: string, timezone?: string) => ({
    id: 'test',
    start,
    end: start,
    title: 'Test',
    allDay: false,
    extendedProps: {
      uid: 'test-uid',
      calendarUrl: '/cal/test/',
      ...(timezone ? { timezone } : {}),
    },
  })

  const makeAllDayEcEvent = (start: string) => ({
    id: 'test',
    start,
    end: start,
    title: 'Test',
    allDay: true,
    extendedProps: {
      uid: 'test-uid',
      calendarUrl: '/cal/test/',
    },
  })

  // 6.1 All-day event produces DATE type
  it('produces DATE type for all-day events', () => {
    const ecEvent = makeAllDayEcEvent('2026-01-29')
    const icsEvent = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Europe/Paris' })
    expect(icsEvent.start.type).toBe('DATE')
    expect(icsEvent.start.local).toBeUndefined()
  })

  // 6.2 Europe/Paris winter: UTC 14:00 → fake UTC hours 15
  it('creates correct fake UTC for Europe/Paris winter (CET, UTC+1)', () => {
    // This simulates an event displayed at 15:00 Paris local time.
    // EventCalendar gives us "2026-01-29T15:00:00.000" as a local time string.
    // new Date("2026-01-29T15:00:00.000") creates a browser-local Date.
    // The adapter should convert this to 15:00 Paris time in the fake UTC.
    const icsEvent = adapter.toIcsEvent(
      makeEcEvent('2026-01-29T15:00:00.000', 'Europe/Paris'),
      { defaultTimezone: 'Europe/Paris' }
    )
    expect(icsEvent.start.type).toBe('DATE-TIME')
    expect(icsEvent.start.local?.timezone).toBe('Europe/Paris')
    // The fake UTC should have getUTCHours() = 15 (Paris local time)
    expect(icsEvent.start.date.getUTCHours()).toBe(15)
    expect(icsEvent.start.date.getUTCMinutes()).toBe(0)
  })

  // 6.3 America/New_York winter: event at 10:00 NY
  it('creates correct fake UTC for America/New_York winter (EST, UTC-5)', () => {
    // An event at 10:00 NY = 15:00 UTC. EventCalendar displays at browser local time.
    // If browser is in Paris (UTC+1), this displays at 16:00.
    // EC string: "2026-01-29T16:00:00.000" parsed as local Paris → UTC 15:00
    // Adapter converts UTC 15:00 to NY components → hours: 10
    const utcDate = new Date('2026-01-29T15:00:00Z')
    // We need to pass a local time string that corresponds to UTC 15:00
    // Since we can't know the CI timezone, use the UTC date directly
    // and test via the adapter's internal conversion
    const ecEvent = {
      id: 'test',
      start: utcDate,
      end: utcDate,
      title: 'Test',
      allDay: false,
      extendedProps: {
        uid: 'test-uid',
        calendarUrl: '/cal/test/',
        timezone: 'America/New_York',
      },
    }
    const icsEvent = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'America/New_York' })
    expect(icsEvent.start.date.getUTCHours()).toBe(10)
    expect(icsEvent.start.local?.timezone).toBe('America/New_York')
  })

  // 6.4 Asia/Tokyo: UTC 06:00 → fake UTC hours 15
  it('creates correct fake UTC for Asia/Tokyo (JST, UTC+9)', () => {
    const utcDate = new Date('2026-01-29T06:00:00Z')
    const ecEvent = {
      id: 'test',
      start: utcDate,
      end: utcDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/test/', timezone: 'Asia/Tokyo' },
    }
    const icsEvent = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Asia/Tokyo' })
    expect(icsEvent.start.date.getUTCHours()).toBe(15)
  })

  // 6.5 Europe/Paris summer (DST): UTC 13:00 → fake UTC hours 15
  it('creates correct fake UTC for Europe/Paris summer (CEST, UTC+2)', () => {
    const utcDate = new Date('2026-07-15T13:00:00Z')
    const ecEvent = {
      id: 'test',
      start: utcDate,
      end: utcDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/test/', timezone: 'Europe/Paris' },
    }
    const icsEvent = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Europe/Paris' })
    expect(icsEvent.start.date.getUTCHours()).toBe(15)
  })

  // 6.6 Preserves minutes and seconds
  it('preserves non-zero minutes and seconds in fake UTC', () => {
    const utcDate = new Date('2026-01-29T14:37:42Z')
    const ecEvent = {
      id: 'test',
      start: utcDate,
      end: utcDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/test/', timezone: 'Europe/Paris' },
    }
    const icsEvent = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Europe/Paris' })
    expect(icsEvent.start.date.getUTCHours()).toBe(15)
    expect(icsEvent.start.date.getUTCMinutes()).toBe(37)
    expect(icsEvent.start.date.getUTCSeconds()).toBe(42)
  })

  // 6.7 Day change: UTC 23:00 + Tokyo → next day
  it('handles day change in fake UTC (UTC 23:00 → next day in Tokyo)', () => {
    const utcDate = new Date('2026-01-29T23:00:00Z')
    const ecEvent = {
      id: 'test',
      start: utcDate,
      end: utcDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/test/', timezone: 'Asia/Tokyo' },
    }
    const icsEvent = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Asia/Tokyo' })
    expect(icsEvent.start.date.getUTCDate()).toBe(30)
    expect(icsEvent.start.date.getUTCHours()).toBe(8)
  })

  // 6.8 local.timezone is correctly set
  it('sets local.timezone on the returned IcsDateObject', () => {
    const utcDate = new Date('2026-01-29T14:00:00Z')
    const ecEvent = {
      id: 'test',
      start: utcDate,
      end: utcDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/test/', timezone: 'America/New_York' },
    }
    const icsEvent = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'America/New_York' })
    expect(icsEvent.start.local?.timezone).toBe('America/New_York')
  })

  // 6.9 local.tzoffset is correctly calculated
  it('calculates correct local.tzoffset format', () => {
    // Winter Paris = +0100
    const winterDate = new Date('2026-01-29T14:00:00Z')
    const winterEvent = {
      id: 'test',
      start: winterDate,
      end: winterDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/test/', timezone: 'Europe/Paris' },
    }
    const winterIcs = adapter.toIcsEvent(winterEvent, { defaultTimezone: 'Europe/Paris' })
    expect(winterIcs.start.local?.tzoffset).toBe('+0100')

    // Summer Paris = +0200
    const summerDate = new Date('2026-07-15T13:00:00Z')
    const summerEvent = {
      id: 'test',
      start: summerDate,
      end: summerDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/test/', timezone: 'Europe/Paris' },
    }
    const summerIcs = adapter.toIcsEvent(summerEvent, { defaultTimezone: 'Europe/Paris' })
    expect(summerIcs.start.local?.tzoffset).toBe('+0200')
  })
})

// ============================================================================
// 7. getTimezoneOffset
// ============================================================================
describe('getTimezoneOffset', () => {
  // 7.1 Positive offset winter
  it('returns "+0100" for Europe/Paris in winter', () => {
    const date = new Date('2026-01-29T14:00:00Z')
    expect(adapter.getTimezoneOffset(date, 'Europe/Paris')).toBe('+0100')
  })

  // 7.2 Positive offset summer
  it('returns "+0200" for Europe/Paris in summer', () => {
    const date = new Date('2026-07-15T13:00:00Z')
    expect(adapter.getTimezoneOffset(date, 'Europe/Paris')).toBe('+0200')
  })

  // 7.3 Negative offset winter
  it('returns "-0500" for America/New_York in winter', () => {
    const date = new Date('2026-01-29T15:00:00Z')
    expect(adapter.getTimezoneOffset(date, 'America/New_York')).toBe('-0500')
  })

  // 7.4 Negative offset summer
  it('returns "-0400" for America/New_York in summer', () => {
    const date = new Date('2026-07-15T14:00:00Z')
    expect(adapter.getTimezoneOffset(date, 'America/New_York')).toBe('-0400')
  })

  // 7.5 Zero offset
  it('returns "+0000" for UTC', () => {
    const date = new Date('2026-01-29T14:00:00Z')
    expect(adapter.getTimezoneOffset(date, 'UTC')).toBe('+0000')
  })

  // 7.6 Half-hour offset
  it('returns "+0530" for Asia/Kolkata', () => {
    const date = new Date('2026-01-29T10:00:00Z')
    expect(adapter.getTimezoneOffset(date, 'Asia/Kolkata')).toBe('+0530')
  })

  // 7.7 Invalid timezone falls back gracefully
  it('returns "+0000" for invalid timezone', () => {
    const date = new Date('2026-01-29T14:00:00Z')
    expect(adapter.getTimezoneOffset(date, 'Invalid/Timezone')).toBe('+0000')
  })
})

// ============================================================================
// 8. Round-trip tests (ICS parse → adapter → display → adapter → ICS)
// ============================================================================
describe('Round-trip conversions', () => {
  /**
   * Simulate a round-trip:
   * 1. Start with an IcsDateObject (as ts-ics would produce from parsing)
   * 2. Convert to JS Date via icsDateToJsDate (read path)
   * 3. Convert to display string via dateToLocalISOString (what EventCalendar sees)
   * 4. Parse the string back (what happens when saving)
   * 5. Convert back to IcsDateObject via toIcsEvent (write path)
   * 6. Verify the fake UTC has the correct hours for ts-ics
   */

  // 8.1 Europe/Paris winter
  it('round-trips Europe/Paris winter event correctly', () => {
    // ts-ics produces: date=UTC 14:00, local.date=fakeUTC 15:00
    const icsDate: IcsDateObject = {
      type: 'DATE-TIME',
      date: new Date('2026-01-29T14:00:00Z'),
      local: {
        date: new Date('2026-01-29T15:00:00Z'),
        timezone: 'Europe/Paris',
        tzoffset: '+0100',
      },
    }
    // Step 1: Read path — get true UTC
    const jsDate = icsDateToJsDate(icsDate)
    expect(jsDate.getUTCHours()).toBe(14) // true UTC

    // Step 2: Write path — convert back through adapter
    const ecEvent = {
      id: 'test',
      start: jsDate,
      end: jsDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/', timezone: 'Europe/Paris' },
    }
    const result = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Europe/Paris' })

    // Verify fake UTC has correct Paris local time
    expect(result.start.date.getUTCHours()).toBe(15)
    expect(result.start.date.getUTCMinutes()).toBe(0)
    expect(result.start.local?.timezone).toBe('Europe/Paris')
  })

  // 8.2 Europe/Paris summer (CEST)
  it('round-trips Europe/Paris summer event correctly', () => {
    const icsDate: IcsDateObject = {
      type: 'DATE-TIME',
      date: new Date('2026-07-15T13:00:00Z'),
      local: {
        date: new Date('2026-07-15T15:00:00Z'),
        timezone: 'Europe/Paris',
        tzoffset: '+0200',
      },
    }
    const jsDate = icsDateToJsDate(icsDate)
    expect(jsDate.getUTCHours()).toBe(13)

    const ecEvent = {
      id: 'test',
      start: jsDate,
      end: jsDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/', timezone: 'Europe/Paris' },
    }
    const result = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Europe/Paris' })
    expect(result.start.date.getUTCHours()).toBe(15)
  })

  // 8.3 America/New_York
  it('round-trips America/New_York event correctly', () => {
    // 10:00 NY = 15:00 UTC
    const icsDate: IcsDateObject = {
      type: 'DATE-TIME',
      date: new Date('2026-01-29T15:00:00Z'),
      local: {
        date: new Date('2026-01-29T10:00:00Z'),
        timezone: 'America/New_York',
        tzoffset: '-0500',
      },
    }
    const jsDate = icsDateToJsDate(icsDate)
    expect(jsDate.getUTCHours()).toBe(15)

    const ecEvent = {
      id: 'test',
      start: jsDate,
      end: jsDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/', timezone: 'America/New_York' },
    }
    const result = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'America/New_York' })
    expect(result.start.date.getUTCHours()).toBe(10) // NY local time preserved
  })

  // 8.4 Asia/Tokyo
  it('round-trips Asia/Tokyo event correctly', () => {
    // 15:00 Tokyo = 06:00 UTC
    const icsDate: IcsDateObject = {
      type: 'DATE-TIME',
      date: new Date('2026-01-29T06:00:00Z'),
      local: {
        date: new Date('2026-01-29T15:00:00Z'),
        timezone: 'Asia/Tokyo',
        tzoffset: '+0900',
      },
    }
    const jsDate = icsDateToJsDate(icsDate)

    const ecEvent = {
      id: 'test',
      start: jsDate,
      end: jsDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/', timezone: 'Asia/Tokyo' },
    }
    const result = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Asia/Tokyo' })
    expect(result.start.date.getUTCHours()).toBe(15) // Tokyo local time preserved
  })

  // 8.5 UTC pure (no TZID)
  it('round-trips pure UTC event correctly', () => {
    const icsDate: IcsDateObject = {
      type: 'DATE-TIME',
      date: new Date('2026-01-29T14:00:00Z'),
      // no local property — pure UTC
    }
    const jsDate = icsDateToJsDate(icsDate)
    expect(jsDate.getUTCHours()).toBe(14)

    // Without a timezone in extProps, adapter uses defaultTimezone
    const ecEvent = {
      id: 'test',
      start: jsDate,
      end: jsDate,
      title: 'Test',
      allDay: false,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/' },
    }
    const result = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'UTC' })
    expect(result.start.date.getUTCHours()).toBe(14)
    expect(result.start.local?.timezone).toBe('UTC')
  })

  // 8.6 All-day event
  it('round-trips all-day event correctly', () => {
    const icsDate: IcsDateObject = {
      type: 'DATE',
      date: new Date('2026-01-29T00:00:00Z'),
    }
    const jsDate = icsDateToJsDate(icsDate)
    expect(jsDate.getUTCDate()).toBe(29)

    const ecEvent = {
      id: 'test',
      start: '2026-01-29',
      end: '2026-01-29',
      title: 'Test',
      allDay: true,
      extendedProps: { uid: 'test-uid', calendarUrl: '/cal/' },
    }
    const result = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'Europe/Paris' })
    expect(result.start.type).toBe('DATE')
    expect(result.start.date.getUTCDate()).toBe(29)
  })

  // 8.7 Cross-timezone (NY event viewed from Paris browser)
  it('preserves NY time after round-trip from Paris browser', () => {
    // NY event at 10:00 = UTC 15:00
    // Paris browser shows at 16:00 local (UTC+1 winter)
    const icsDate: IcsDateObject = {
      type: 'DATE-TIME',
      date: new Date('2026-01-29T15:00:00Z'), // true UTC
      local: {
        date: new Date('2026-01-29T10:00:00Z'), // fake UTC for NY
        timezone: 'America/New_York',
        tzoffset: '-0500',
      },
    }

    // Read: returns true UTC (15:00 UTC)
    const jsDate = icsDateToJsDate(icsDate)
    expect(jsDate.getUTCHours()).toBe(15)

    // Write: adapter converts UTC 15:00 back to NY timezone → 10:00 fake UTC
    const ecEvent = {
      id: 'test',
      start: jsDate,
      end: jsDate,
      title: 'NY Meeting',
      allDay: false,
      extendedProps: {
        uid: 'test-uid',
        calendarUrl: '/cal/',
        timezone: 'America/New_York', // original timezone preserved in extProps
      },
    }
    const result = adapter.toIcsEvent(ecEvent, { defaultTimezone: 'America/New_York' })

    // NY local time preserved despite being viewed from Paris
    expect(result.start.date.getUTCHours()).toBe(10)
    expect(result.start.date.getUTCMinutes()).toBe(0)
    expect(result.start.local?.timezone).toBe('America/New_York')
  })
})
