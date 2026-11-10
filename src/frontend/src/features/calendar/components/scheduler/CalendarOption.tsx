import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { DEFAULT_EVENT_COLOR } from "@/features/calendar/constants";
import { CalendarGroupIcon } from "../CalendarGroupIcon";

/** A calendar in the select of the event form: its colour, its name and its group icon. */
export function CalendarOption({ calendar }: { calendar: CalDavCalendar }) {
  const color = calendar.color || DEFAULT_EVENT_COLOR;
  return (
    <span className="calendar-select__option">
      <span className="calendar-select__color" style={{ backgroundColor: color }} />
      {calendar.displayName || calendar.url}
      <CalendarGroupIcon calendar={calendar} className="calendar-list__group-icon" />
    </span>
  );
}
