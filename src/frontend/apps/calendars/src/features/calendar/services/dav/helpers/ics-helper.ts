import type { IcsEvent } from 'ts-ics'

export function isEventAllDay(event: IcsEvent) {
  return event.start.type === 'DATE' || event.end?.type === 'DATE'
}
