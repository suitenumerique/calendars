import type { IcsDateObject, IcsEvent } from "ts-ics";

import { withPartstatsFrom, withSeriesAttendeeChange } from "./series-attendees";
import { toWallClock } from "./timezone";

/** The VEVENTs of a new series: the master and its overrides. */
export interface SplitSeries {
  master: IcsEvent;
  overrides: IcsEvent[];
}

/**
 * Give the wall-clock time of a date in the timezone ("fake UTC"). A
 * date, or no timezone, keeps the value.
 */
const wallClock = (value: IcsDateObject, timezone: string | undefined): Date => {
  if (!timezone || value.type === "DATE") return value.date;
  if (value.local?.timezone === timezone) return value.local.date;
  return toWallClock(value.date, timezone);
};

/** Give a date at the wall-clock time, in the format of the start of the master. */
const atWallClock = (master: IcsEvent, wall: Date): IcsDateObject => ({
  date: wall,
  type: master.start.type,
  local: master.start.local && { ...master.start.local, date: wall },
});

/**
 * Build the new series of a "this and future" edit.
 *
 * `newMaster` is the edited occurrence, with the UID and the RRULE of the
 * new series. `cutoff` is the original time of the edited occurrence, as
 * wall-clock time in the timezone of `oldMaster`.
 *
 * The attendees keep the PARTSTAT of the old master, not the answer for
 * one date. The overrides and EXDATEs after the cutoff move to the new
 * series. Their RECURRENCE-ID moves with the new start. An override that
 * does not move its date moves with the new start too. The overrides get
 * the attendee change of the edit. An answer for the edited occurrence
 * stays on the first date of the new series.
 */
export const splitSeries = (
  source: IcsEvent[],
  oldMaster: IcsEvent,
  newMaster: IcsEvent,
  cutoff: Date,
): SplitSeries => {
  const timezone = oldMaster.start.local?.timezone;
  const newStart = newMaster.start.local?.date ?? newMaster.start.date;
  const offset = newStart.getTime() - cutoff.getTime();
  const fromCutoff = (value: IcsDateObject): number =>
    wallClock(value, timezone).getTime() - cutoff.getTime();
  const shift = (value: IcsDateObject): IcsDateObject =>
    atWallClock(newMaster, new Date(wallClock(value, timezone).getTime() + offset));

  const exceptionDates = oldMaster.exceptionDates?.filter((d) => fromCutoff(d) > 0).map(shift);
  const master: IcsEvent = {
    ...newMaster,
    attendees: withPartstatsFrom(newMaster.attendees, oldMaster),
    exceptionDates: exceptionDates?.length ? exceptionDates : undefined,
  };

  const overrides = source.filter((e) => e.uid === oldMaster.uid && e.recurrenceId);
  const moveOverride = (override: IcsEvent): IcsEvent => {
    const recurrenceId = override.recurrenceId!;
    const event = withSeriesAttendeeChange(override, oldMaster, master);
    const moved = {
      ...event,
      uid: master.uid,
      recurrenceId: { ...recurrenceId, value: shift(recurrenceId.value) },
    };
    const ownTime = fromCutoff(override.start) !== fromCutoff(recurrenceId.value);
    if (ownTime) return moved;
    return {
      ...moved,
      start: shift(override.start),
      ...(override.end && { end: shift(override.end) }),
    } as IcsEvent;
  };
  const moved = overrides.filter((e) => fromCutoff(e.recurrenceId!.value) > 0).map(moveOverride);

  const edited = overrides.find((e) => fromCutoff(e.recurrenceId!.value) === 0);
  const answers = edited && withPartstatsFrom(master.attendees, edited);
  const answered = answers?.some((a, i) => a.partstat !== master.attendees?.[i].partstat);
  if (!answered) return { master, overrides: moved };

  const first: IcsEvent = {
    ...master,
    recurrenceRule: undefined,
    exceptionDates: undefined,
    recurrenceId: { value: atWallClock(master, newStart) },
    attendees: answers,
  };
  return { master, overrides: [first, ...moved] };
};
