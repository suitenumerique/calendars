import type { CalDavCalendar } from "../services/dav/types/caldav-service";
import { compareCalendarGroups } from "./calendar-ownership";

/**
 * Compare by saved `calendar-order`, with a missing order last. Break
 * ties by group, then by name, then by URL. The URL keeps the order of
 * two calendars with the same name when the user hides one of them.
 */
const compareCalendars = (a: CalDavCalendar, b: CalDavCalendar): number => {
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

/**
 * The calendar of a new event: the first calendar that is not read-only,
 * or the first calendar when all are. Undefined for an empty list. The
 * list must be in display order.
 */
export const getDefaultCalendar = (calendars: CalDavCalendar[]): CalDavCalendar | undefined =>
  calendars.find((calendar) => !calendar.readOnly) ?? calendars[0];
