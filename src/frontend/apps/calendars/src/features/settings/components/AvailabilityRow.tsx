import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import {
  DAYS_OF_WEEK,
  type AvailabilitySlot,
  type AvailabilityWhen,
  type DayOfWeek,
} from "../types";

interface AvailabilityRowProps {
  slot: AvailabilitySlot;
  onChange: (id: string, updates: Partial<AvailabilitySlot>) => void;
  onDelete: (id: string) => void;
}

export const AvailabilityRow = ({
  slot,
  onChange,
  onDelete,
}: AvailabilityRowProps) => {
  const { t } = useTranslation();

  const selectValue =
    slot.when.type === "recurring" ? slot.when.day : "specific";

  const handleWhenChange = useCallback(
    (value: string) => {
      let when: AvailabilityWhen;
      if (value === "specific") {
        // Default to today's date
        const today = new Date().toISOString().split("T")[0];
        when = { type: "specific", date: today };
      } else {
        when = { type: "recurring", day: value as DayOfWeek };
      }
      onChange(slot.id, { when });
    },
    [onChange, slot.id],
  );

  const handleDateChange = useCallback(
    (date: string) => {
      onChange(slot.id, {
        when: { type: "specific", date },
      });
    },
    [onChange, slot.id],
  );

  return (
    <div className="working-hours__row">
      <div className="working-hours__row-when">
        <select
          className="working-hours__select"
          value={selectValue}
          onChange={(e) => handleWhenChange(e.target.value)}
        >
          {DAYS_OF_WEEK.map((day) => (
            <option key={day} value={day}>
              {t(`settings.workingHours.every${day.charAt(0).toUpperCase() + day.slice(1)}`)}
            </option>
          ))}
          <option value="specific">
            {t("settings.workingHours.specificDate")}
          </option>
        </select>
        {slot.when.type === "specific" && (
          <input
            type="date"
            className="working-hours__date-input"
            value={slot.when.date}
            onChange={(e) => handleDateChange(e.target.value)}
          />
        )}
      </div>

      <input
        type="time"
        className="working-hours__row-time"
        value={slot.start}
        onChange={(e) => onChange(slot.id, { start: e.target.value })}
      />

      <input
        type="time"
        className="working-hours__row-time"
        value={slot.end}
        onChange={(e) => onChange(slot.id, { end: e.target.value })}
      />

      <button
        type="button"
        className="working-hours__row-delete"
        onClick={() => onDelete(slot.id)}
        aria-label={t("settings.workingHours.removeAvailability")}
      >
        <span className="material-icons">close</span>
      </button>
    </div>
  );
};
