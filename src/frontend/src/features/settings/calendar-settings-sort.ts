import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";

/**
 * Sorts the calendars by name, then by URL. The URL keeps the order of
 * two calendars with the same name when the user hides one of them.
 */
export const sortCalendarsForSettings = (calendars: CalDavCalendar[]): CalDavCalendar[] =>
  [...calendars].sort(
    (a, b) => a.displayName.localeCompare(b.displayName) || a.url.localeCompare(b.url),
  );
