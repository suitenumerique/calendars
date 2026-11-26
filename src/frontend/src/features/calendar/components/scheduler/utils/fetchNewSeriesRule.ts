import type { IcsEvent, IcsRecurrenceRule } from "ts-ics";

import type { CalDavService } from "../../../services/dav/CalDavService";
import { getNewSeriesRule } from "./newSeriesRule";

const YEAR_MS = 366 * 24 * 60 * 60 * 1000;
const EPOCH = 0;
const END_OF_TIME = new Date(Date.UTC(2200, 0, 1));

/**
 * Give a range that holds all the occurrences of the series, also the ones
 * that an override moves to an earlier date. It starts in 1970, or one
 * year before an older series.
 */
const rangeOf = (sourceEvent: IcsEvent) => ({
  start: new Date(Math.min(EPOCH, sourceEvent.start.date.getTime() - YEAR_MS)),
  end: END_OF_TIME,
});

/**
 * Get the recurrence rule of the series that starts at `cutoff` when the
 * series at `eventUrl` splits in two. Only a rule with a COUNT needs the
 * occurrences from the server.
 */
export const fetchNewSeriesRule = async (
  caldavService: CalDavService,
  eventUrl: string,
  sourceEvent: IcsEvent,
  cutoff: Date,
): Promise<IcsRecurrenceRule | undefined> => {
  if (!sourceEvent.recurrenceRule?.count) return sourceEvent.recurrenceRule;

  const result = await caldavService.fetchOccurrenceDates(
    eventUrl,
    sourceEvent.uid,
    rangeOf(sourceEvent),
  );
  if (!result.success || !result.data) {
    throw new Error(result.error || "Failed to expand series");
  }
  return getNewSeriesRule(sourceEvent, cutoff, result.data);
};
