import type { IcsDateObject } from "ts-ics";

import type { RsvpBlocker } from "../../../services/dav/types/caldav-service";

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
export const toOccurrenceInstant = (value: IcsDateObject): Date => {
  const date = new Date(value.date);
  if (value.type === "DATE" || !value.local) return date;
  return new Date(date.getTime() - offsetMs(value.local.tzoffset));
};

export const RSVP_BLOCKER_MESSAGE_KEYS: Record<RsvpBlocker, string> = {
  cancelled: "rsvp.error.eventCancelled",
  deleted: "rsvp.error.eventNotFound",
  notAttendee: "rsvp.error.notAttendee",
};
