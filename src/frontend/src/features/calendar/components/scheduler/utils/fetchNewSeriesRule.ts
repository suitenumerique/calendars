import type { IcsEvent, IcsRecurrenceRule } from "ts-ics";

import type { CalDavService } from "../../../services/dav/CalDavService";
import { getNewSeriesRule } from "./newSeriesRule";

// The range holds all the occurrences, also the ones that an override moves.
const ALL_TIME = {
  start: new Date(Date.UTC(1970, 0, 1)),
  end: new Date(Date.UTC(2200, 0, 1)),
};

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

  const result = await caldavService.fetchOccurrenceDates(eventUrl, sourceEvent.uid, ALL_TIME);
  if (!result.success || !result.data) {
    throw new Error(result.error || "Failed to expand series");
  }
  return getNewSeriesRule(sourceEvent, cutoff, result.data);
};
