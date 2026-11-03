import type { ReactNode } from "react";

import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { CalendarSettingsRow } from "./CalendarSettingsRow";

interface CalendarSettingsSectionProps {
  title: string;
  /** The text that replaces the list when it is empty. */
  emptyText: string;
  calendars: CalDavCalendar[];
  renderActions?: (calendar: CalDavCalendar) => ReactNode;
}

export const CalendarSettingsSection = ({
  title,
  emptyText,
  calendars,
  renderActions,
}: CalendarSettingsSectionProps) => (
  <section className="calendar-settings__section">
    <h3 className="calendar-settings__section-title">{title}</h3>
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
