import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Select } from "@gouvfr-lasuite/ui-components";

import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { DEFAULT_EVENT_COLOR } from "@/features/calendar/constants";
import { CalendarGroupIcon } from "../CalendarGroupIcon";

interface CalendarSelectProps {
  calendars: CalDavCalendar[];
  value: string;
  onChange: (url: string) => void;
}

function CalendarOption({ calendar }: { calendar: CalDavCalendar }) {
  const color = calendar.color || DEFAULT_EVENT_COLOR;
  return (
    <span className="calendar-select__option">
      <span className="calendar-select__color" style={{ backgroundColor: color }} />
      {calendar.displayName || calendar.url}
      <CalendarGroupIcon calendar={calendar} className="calendar-list__group-icon" />
    </span>
  );
}

export function CalendarSelect({ calendars, value, onChange }: CalendarSelectProps) {
  const { t } = useTranslation();

  const options = useMemo(
    () =>
      calendars.map((cal) => {
        const optionJsx = <CalendarOption calendar={cal} />;
        return {
          value: cal.url,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          label: optionJsx as any,
          render: () => optionJsx,
        };
      }),
    [calendars],
  );

  return (
    <Select
      label={t("calendar.event.calendar")}
      hideLabel
      value={value}
      onChange={(e) => onChange(String(e.target.value))}
      options={options}
      clearable={false}
      variant="classic"
      fullWidth
    />
  );
}
