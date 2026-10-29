import type { IcsAttendeePartStatusType, IcsDateObject, IcsEvent } from "ts-ics";

import type { RsvpBlocker, RsvpEvent } from "../types";
import { getEventCalendarAdapter } from "../../../services/dav/EventCalendarAdapter";

/**
 * Give the wall-clock time of `date` in `timezone`. The result stores
 * that time in UTC fields ("fake UTC"), so 10:00 in Paris becomes 10:00Z.
 */
const toWallClock = (date: Date, timezone: string): Date => {
  const c = getEventCalendarAdapter().getDateComponentsInTimezone(date, timezone);
  return new Date(Date.UTC(c.year, c.month - 1, c.day, c.hours, c.minutes, c.seconds));
};

/** Give the milliseconds of a UTC offset such as "+0200". */
const offsetMs = (tzoffset: string): number => {
  const m = /^([+-])(\d{2})(\d{2})$/.exec(tzoffset);
  if (!m) return 0;
  const ms = (Number(m[2]) * 60 + Number(m[3])) * 60_000;
  return m[1] === "-" ? -ms : ms;
};

/**
 * Give the instant of an occurrence date from the grid.
 *
 * The grid gives the wall-clock time and the UTC offset of the
 * occurrence. The offset tells apart the two times of the hour that
 * repeats when daylight saving time ends. An all-day date stays at
 * midnight UTC, as in the server expansion.
 */
export const toOccurrenceInstant = (date: Date, value?: IcsDateObject): Date =>
  value?.type === "DATE" || !value?.local
    ? date
    : new Date(date.getTime() - offsetMs(value.local.tzoffset));

const moveTo = (value: IcsDateObject, date: Date): IcsDateObject => ({
  ...value,
  date,
  local: value.local && { ...value.local, date: toWallClock(date, value.local.timezone) },
});

/**
 * Copy the master to one occurrence. Move the dates to the occurrence.
 * Remove the series fields (RRULE, EXDATE).
 */
const occurrenceOf = (master: IcsEvent, instant: Date): IcsEvent => {
  const offset = instant.getTime() - master.start.date.getTime();
  const start = moveTo(master.start, instant);
  const moved: IcsEvent = master.end
    ? { ...master, start, end: moveTo(master.end, new Date(master.end.date.getTime() + offset)) }
    : { ...master, start };
  return { ...moved, recurrenceRule: undefined, exceptionDates: undefined };
};

/** Find the override VEVENT whose RECURRENCE-ID is at `instant`. */
const findOverride = (instances: IcsEvent[], instant: Date): IcsEvent | undefined =>
  instances.find((e) => e.recurrenceId?.value.date.getTime() === instant.getTime());

/**
 * Find the VEVENTs of one event in the server copy. Give `instant` to
 * also find the override of that occurrence.
 */
export const resolveRsvpEvent = (
  events: IcsEvent[] | undefined,
  uid: string,
  instant?: Date,
): RsvpEvent => {
  const instances = events?.filter((e) => e.uid === uid) ?? [];
  return {
    instances,
    master: instances.find((e) => !e.recurrenceId),
    override: instant && findOverride(instances, instant),
  };
};

/**
 * Give the occurrence date as the wall-clock time in the timezone of the
 * series ("fake UTC"). `createOverrideInstance` expects this format. An
 * all-day date, or a series without timezone, keeps the instant.
 */
export const toSeriesWallClock = (master: IcsEvent | undefined, instant: Date): Date => {
  const start = master?.start;
  return start?.type === "DATE" || !start?.local
    ? instant
    : toWallClock(instant, start.local.timezone);
};

/**
 * Build the event data of the answer to one occurrence. The base is the
 * override of the occurrence. If there is no override, the base is a copy
 * of the master at the occurrence. Only the PARTSTAT of the attendee
 * changes. `createOverrideInstance` sets the RECURRENCE-ID.
 *
 * The function returns undefined if the event has no override and no
 * master.
 */
export const buildOccurrenceReply = (
  { master, override }: RsvpEvent,
  instant: Date,
  attendeeEmail: string,
  partstat: IcsAttendeePartStatusType,
): IcsEvent | undefined => {
  const base = override ?? (master && occurrenceOf(master, instant));
  if (!base) return undefined;

  const email = attendeeEmail.toLowerCase();
  return {
    ...base,
    attendees: base.attendees?.map((a) =>
      a.email.toLowerCase() === email ? { ...a, partstat } : a,
    ),
  };
};

export const RSVP_BLOCKER_MESSAGE_KEYS: Record<RsvpBlocker, string> = {
  cancelled: "rsvp.error.eventCancelled",
  deleted: "rsvp.error.eventNotFound",
  notAttendee: "rsvp.error.notAttendee",
};

/**
 * Find why an attendee cannot answer an invitation.
 *
 * Give `scheduled` to check one occurrence: it tells if the occurrence
 * still exists. An occurrence is cancelled when it is not scheduled, or
 * when its override has STATUS:CANCELLED.
 *
 * Returns null when the attendee can answer.
 */
export const findRsvpBlocker = (
  { instances, master, override }: RsvpEvent,
  attendeeEmail: string,
  scheduled?: boolean,
): RsvpBlocker | null => {
  if (instances.length === 0) return "deleted";
  if (master?.status === "CANCELLED") return "cancelled";

  let target = master;
  if (scheduled !== undefined) {
    if (!scheduled || override?.status === "CANCELLED") return "cancelled";
    target = override ?? master;
  }

  const email = attendeeEmail.toLowerCase();
  const isAttendee = target?.attendees?.some((a) => a.email.toLowerCase() === email);
  return isAttendee ? null : "notAttendee";
};
