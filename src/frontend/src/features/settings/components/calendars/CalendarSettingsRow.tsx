import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Mail } from "@gouvfr-lasuite/ui-components/icons";

import { DEFAULT_EVENT_COLOR } from "@/features/calendar/constants";
import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";

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
      {calendar.mailboxEmail && (
        <span
          className="calendar-settings__mailbox"
          title={t("calendar.list.mailboxCalendar", { email: calendar.mailboxEmail })}
        >
          <Mail className="calendar-settings__mailbox-icon" aria-hidden />
          <span className="calendar-settings__mailbox-email">{calendar.mailboxEmail}</span>
        </span>
      )}
      {actions && <div className="calendar-settings__actions">{actions}</div>}
    </li>
  );
};
