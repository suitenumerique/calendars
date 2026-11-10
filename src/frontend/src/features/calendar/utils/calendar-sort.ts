import type { CalDavCalendar } from "../services/dav/types/caldav-service";
import { compareCalendarGroups } from "./calendar-ownership";

/**
 * Order the calendars as the user placed them. A calendar without a
 * `calendar-order` goes after the placed ones, by group, then by name.
 * The URL keeps the order of two calendars with the same name when the
 * user hides one of them.
 */
export const compareCalendars = (a: CalDavCalendar, b: CalDavCalendar): number => {
  const ao = a.order ?? Number.POSITIVE_INFINITY;
  const bo = b.order ?? Number.POSITIVE_INFINITY;
  if (ao !== bo) return ao - bo;
  return (
    compareCalendarGroups(a, b) ||
    a.displayName.localeCompare(b.displayName) ||
    a.url.localeCompare(b.url)
  );
};

export const sortCalendars = (calendars: CalDavCalendar[]): CalDavCalendar[] =>
  [...calendars].sort(compareCalendars);
