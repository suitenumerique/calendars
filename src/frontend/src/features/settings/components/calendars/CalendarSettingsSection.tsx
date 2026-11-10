import type { ReactNode } from "react";

import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { CalendarSettingsRow } from "./CalendarSettingsRow";

interface CalendarSettingsSectionProps {
  /** The text that replaces the list when it is empty. */
  emptyText: string;
  calendars: CalDavCalendar[];
  renderActions?: (calendar: CalDavCalendar) => ReactNode;
}

export const CalendarSettingsSection = ({
  emptyText,
  calendars,
  renderActions,
}: CalendarSettingsSectionProps) => (
  <section className="calendar-settings__section">
    {calendars.length === 0 ? (
      <p className="calendar-settings__empty">{emptyText}</p>
    ) : (
      <ul className="calendar-settings__list">
        {calendars.map((calendar) => (
          <CalendarSettingsRow
            key={calendar.url}
            calendar={calendar}
            actions={renderActions?.(calendar)}
          />
        ))}
      </ul>
    )}
  </section>
);
