import type { IcsEvent, IcsRecurrenceRule } from "ts-ics";

import { toSeriesWallClock } from "../../../services/dav/helpers/rsvp";

/**
 * Get the recurrence rule of the series that starts at `cutoff` when a
 * series splits in two. `cutoff` is the first occurrence of the new
 * series, in fake UTC. `occurrences` are the instants of the occurrences
 * of the source series, without the EXDATEs, as the server expands them.
 *
 * A rule with a COUNT gets the number of occurrences from the cutoff.
 * COUNT also counts the occurrences that an EXDATE removes. Other rules
 * do not change.
 */
export const getNewSeriesRule = (
  sourceEvent: IcsEvent,
  cutoff: Date,
  occurrences: Date[],
): IcsRecurrenceRule | undefined => {
  const rule = sourceEvent.recurrenceRule;
  if (!rule?.count) return rule;

  const excluded = (sourceEvent.exceptionDates ?? []).map((d) => d.date);
  const before = new Set(
    [...occurrences, ...excluded]
      .map((d) => toSeriesWallClock(sourceEvent, d).getTime())
      .filter((t) => t < cutoff.getTime()),
  ).size;

  return { ...rule, count: Math.max(rule.count - before, 1) };
};
