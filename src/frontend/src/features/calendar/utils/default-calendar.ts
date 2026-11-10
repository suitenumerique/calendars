import type { CalDavCalendar } from "../services/dav/types/caldav-service";

/**
 * The calendar of a new event: the first calendar of the list that the
 * user can write to. When every calendar is read-only, the first one,
 * so the user gets the error of the server and not an empty form.
 */
export const getDefaultCalendar = (calendars: CalDavCalendar[]): CalDavCalendar | undefined =>
  calendars.find((calendar) => !calendar.readOnly) ?? calendars[0];
