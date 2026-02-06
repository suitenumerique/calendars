import { useTranslation } from "react-i18next";
import { Input } from "@gouvfr-lasuite/cunningham-react";
import { SectionRow } from "./SectionRow";

interface DateTimeSectionProps {
  startDateTime: string;
  endDateTime: string;
  isAllDay: boolean;
  onStartChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onEndChange: (value: string) => void;
  onAllDayChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export const DateTimeSection = ({
  startDateTime,
  endDateTime,
  isAllDay,
  onStartChange,
  onEndChange,
  onAllDayChange,
}: DateTimeSectionProps) => {
  const { t } = useTranslation();

  return (
    <div>
      <SectionRow
        icon="access_time"
        label={t("calendar.event.sections.addDateTime")}
        isEmpty={!startDateTime || !endDateTime}
        alwaysOpen={true}
        iconAlign="flex-start"
      >
        <div className="datetime-section">
          <div className="datetime-section__inputs">
            <Input
              type={isAllDay ? "date" : "datetime-local"}
              label={t("calendar.event.start")}
              value={startDateTime}
              onChange={onStartChange}
              fullWidth
              hideLabel
              variant="classic"
            />
            <span
              className="material-icons datetime-section__arrow"
              aria-hidden="true"
            >
              arrow_forward
            </span>
            <Input
              type={isAllDay ? "date" : "datetime-local"}
              label={t("calendar.event.end")}
              value={endDateTime}
              onChange={(e) => onEndChange(e.target.value)}
              fullWidth
              hideLabel
              variant="classic"
            />
          </div>
          <label className="datetime-section__allday">
            <input
              type="checkbox"
              checked={isAllDay}
              onChange={onAllDayChange}
            />
            <span>{t("calendar.event.allDay")}</span>
          </label>
        </div>
      </SectionRow>
    </div>
  );
};
