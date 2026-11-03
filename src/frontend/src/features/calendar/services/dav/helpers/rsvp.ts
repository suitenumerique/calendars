import type { IcsAttendeePartStatusType, IcsDateObject, IcsEvent } from "ts-ics";

import type { RsvpBlocker } from "../types/caldav-service";
import { toWallClock } from "./timezone";

/** The VEVENTs of one event in the server copy, found once per response. */
export interface RsvpEvent {
  /** All VEVENTs with the UID of the event. */
  instances: IcsEvent[];
  /** The VEVENT without RECURRENCE-ID. */
  master?: IcsEvent;
  /** The override of the occurrence, if any. */
  override?: IcsEvent;
}

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
  const start = moveTo(master.start, instant);
  const series = { recurrenceRule: undefined, exceptionDates: undefined };
  if (!master.end) return { ...master, ...series, start };

  const offset = instant.getTime() - master.start.date.getTime();
  const end = moveTo(master.end, new Date(master.end.date.getTime() + offset));
  return { ...master, ...series, start, end };
};

/**
 * Find the VEVENTs of one event in the server copy. Give `instant` to
 * also find the override of that occurrence.
 *
 * An attendee invited to one occurrence only gets a copy without master.
 * Without `instant`, the single VEVENT of such a copy is the override.
 */
export const resolveRsvpEvent = (
  events: IcsEvent[] | undefined,
  uid: string,
  instant?: Date,
): RsvpEvent => {
  const instances = events?.filter((e) => e.uid === uid) ?? [];
  const master = instances.find((e) => !e.recurrenceId);
  const override = instant
    ? instances.find((e) => e.recurrenceId?.value.date.getTime() === instant.getTime())
    : !master && instances.length === 1
      ? instances[0]
      : undefined;
  return { instances, master, override };
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

/** Copy the event with a new PARTSTAT for the attendee. */
export const withPartstat = (
  event: IcsEvent,
  attendeeEmail: string,
  partstat: IcsAttendeePartStatusType,
): IcsEvent => {
  const email = attendeeEmail.toLowerCase();
  return {
    ...event,
    attendees: event.attendees?.map((a) =>
      a.email.toLowerCase() === email ? { ...a, partstat } : a,
    ),
  };
};

/**
 * Build the event data of the response to one occurrence. The base is the
 * override of the occurrence. If there is no override, the base is a copy
 * of the master at the occurrence. The function sets the PARTSTAT of the
 * attendee in the base. `createOverrideInstance` then writes it: it sets
 * the RECURRENCE-ID and increments SEQUENCE.
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
  return base && withPartstat(base, attendeeEmail, partstat);
};

/**
 * Find why an attendee cannot respond to an invitation.
 *
 * Give `scheduled` to check one occurrence. `scheduled` only tells if the
 * occurrence is present in the event. A missing occurrence is cancelled.
 * A present occurrence can still block the response: when its override
 * has STATUS:CANCELLED, or when its override or the master does not list
 * the attendee.
 *
 * Returns null when the attendee can respond.
 */
export const findRsvpBlocker = (
  { instances, master, override }: RsvpEvent,
  attendeeEmail: string,
  scheduled?: boolean,
): RsvpBlocker | null => {
  if (instances.length === 0) return "deleted";
  if (master?.status === "CANCELLED") return "cancelled";

  if (scheduled === false || override?.status === "CANCELLED") return "cancelled";

  const target = override ?? master;
  const email = attendeeEmail.toLowerCase();
  const isAttendee = target?.attendees?.some((a) => a.email.toLowerCase() === email);
  return isAttendee ? null : "notAttendee";
};
