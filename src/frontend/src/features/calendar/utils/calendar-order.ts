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

/**
 * The calendar of a new event: the first calendar of the list that the
 * user can write to. When every calendar is read-only, the first one,
 * so the user gets the error of the server and not an empty form.
 */
export const getDefaultCalendar = (calendars: CalDavCalendar[]): CalDavCalendar | undefined =>
  calendars.find((calendar) => !calendar.readOnly) ?? calendars[0];
