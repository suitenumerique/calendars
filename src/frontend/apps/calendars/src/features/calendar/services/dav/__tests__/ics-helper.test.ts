/**
 * Tests for ICS Helper functions
 */
import type { IcsEvent } from 'ts-ics'
import { isEventAllDay } from '../helpers/ics-helper'

describe('ics-helper', () => {
  describe('isEventAllDay', () => {
    it('returns true when start type is DATE', () => {
      const event = {
        start: { type: 'DATE', date: new Date() },
        uid: 'test',
        stamp: { date: new Date() },
      } as IcsEvent

      expect(isEventAllDay(event)).toBe(true)
    })

    it('returns true when end type is DATE', () => {
      const event = {
        start: { type: 'DATE-TIME', date: new Date() },
        end: { type: 'DATE', date: new Date() },
        uid: 'test',
        stamp: { date: new Date() },
      } as IcsEvent

      expect(isEventAllDay(event)).toBe(true)
    })

    it('returns false when both start and end are DATE-TIME', () => {
      const event = {
        start: { type: 'DATE-TIME', date: new Date() },
        end: { type: 'DATE-TIME', date: new Date() },
        uid: 'test',
        stamp: { date: new Date() },
      } as IcsEvent

      expect(isEventAllDay(event)).toBe(false)
    })
  })
})
