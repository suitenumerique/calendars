import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { CalendarGroupIcon } from "@/features/calendar/components/CalendarGroupIcon";
import { DEFAULT_EVENT_COLOR } from "@/features/calendar/constants";
import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { getCalendarGroup } from "@/features/calendar/utils/calendar-ownership";

interface CalendarSettingsRowProps {
  calendar: CalDavCalendar;
  actions?: ReactNode;
}

export const CalendarSettingsRow = ({ calendar, actions }: CalendarSettingsRowProps) => {
  const { t } = useTranslation();
  const color = typeof calendar.color === "string" ? calendar.color : DEFAULT_EVENT_COLOR;
  const nameClassName = calendar.hidden
    ? "calendar-settings__name calendar-settings__name--hidden"
    : "calendar-settings__name";

  return (
    <li className="calendar-settings__row">
      <span className="calendar-settings__color" style={{ backgroundColor: color }} />
      <span className={nameClassName} title={calendar.displayName || undefined}>
        {calendar.displayName || t("calendar.list.unnamed")}
      </span>
      <CalendarGroupIcon calendar={calendar} className="calendar-settings__group-icon" />
      {getCalendarGroup(calendar) === "mailbox" && (
        <span className="calendar-settings__mailbox-email">{calendar.mailboxEmail}</span>
      )}
      {actions && <div className="calendar-settings__actions">{actions}</div>}
    </li>
  );
};
