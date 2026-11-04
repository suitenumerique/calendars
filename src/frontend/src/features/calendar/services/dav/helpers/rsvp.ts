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
 */
export const resolveRsvpEvent = (
  events: IcsEvent[] | undefined,
  uid: string,
  instant?: Date,
): RsvpEvent => {
  const instances = events?.filter((e) => e.uid === uid) ?? [];
  const master = instances.find((e) => !e.recurrenceId);
  const override =
    instant && instances.find((e) => e.recurrenceId?.value.date.getTime() === instant.getTime());
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
 * Give the VEVENTs that a response to all occurrences changes: the master
 * and the overrides that list the attendee. A cancelled override keeps
 * its PARTSTAT.
 */
export const seriesTargets = ({ instances }: RsvpEvent, attendeeEmail: string): IcsEvent[] => {
  const email = attendeeEmail.toLowerCase();
  return instances.filter(
    (e) => e.status !== "CANCELLED" && e.attendees?.some((a) => a.email.toLowerCase() === email),
  );
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
 * A copy without master has only overrides: an attendee invited to some
 * occurrences only gets such a copy. Without override, the function
 * checks all these overrides. The attendee can respond when one of them
 * is not cancelled and lists the attendee.
 *
 * Returns null when the attendee can respond.
 */
export const findRsvpBlocker = (
  { instances, master, override }: RsvpEvent,
  attendeeEmail: string,
  scheduled?: boolean,
): RsvpBlocker | null => {
  if (instances.length === 0) return "deleted";
  if (master?.status === "CANCELLED" || scheduled === false) return "cancelled";

  const target = override ?? master;
  const live = (target ? [target] : instances).filter((e) => e.status !== "CANCELLED");
  if (live.length === 0) return "cancelled";

  const email = attendeeEmail.toLowerCase();
  const listed = live.some((e) => e.attendees?.some((a) => a.email.toLowerCase() === email));
  return listed ? null : "notAttendee";
};
