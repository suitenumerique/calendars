import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Select } from "@gouvfr-lasuite/cunningham-react";
import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";

interface CalendarSelectProps {
  calendars: CalDavCalendar[];
  value: string;
  onChange: (url: string) => void;
}

function CalendarOption({
  name,
  color,
  mailboxEmail,
}: {
  name: string;
  color: string;
  mailboxEmail?: string;
}) {
  return (
    <span className="calendar-select__option">
      <span
        className="calendar-select__color"
        style={{ backgroundColor: color }}
      />
      {name}
      {mailboxEmail && (
        <span
          className="material-icons calendar-list__mailbox-icon"
          title={mailboxEmail}
        >
          mail
        </span>
      )}
    </span>
  );
}

export function CalendarSelect({
  calendars,
  value,
  onChange,
}: CalendarSelectProps) {
  const { t } = useTranslation();

  const options = useMemo(
    () =>
      calendars.map((cal) => {
        const name = cal.displayName || cal.url;
        const color = cal.color || "#3788d8";
        const optionJsx = (
          <CalendarOption
            name={name}
            color={color}
            mailboxEmail={cal.mailboxEmail}
          />
        );
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
