import { belongsInMyCalendars } from "@/features/calendar/utils/calendar-ownership";
import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";

export interface CalendarSettingsGroups {
  /** The calendars of the user and of their mailboxes. */
  mine: CalDavCalendar[];
  /** The calendars that other users share with the user. */
  shared: CalDavCalendar[];
}

/** Splits the calendars like the sidebar does. Each group is sorted by name. */
export const groupCalendarsForSettings = (calendars: CalDavCalendar[]): CalendarSettingsGroups => {
  const sorted = [...calendars].sort((a, b) => a.displayName.localeCompare(b.displayName));
  return {
    mine: sorted.filter(belongsInMyCalendars),
    shared: sorted.filter((calendar) => !belongsInMyCalendars(calendar)),
  };
};
