import { useMemo } from "react";
import { isSameDay, isWeekend } from "@/utils/date";

import type { WeekDayBarProps } from "../types";

export const WeekDayBar = ({
  currentDate,
  currentView,
  intlLocale,
  weekDays,
  onDayClick,
}: WeekDayBarProps) => {
  const today = useMemo(() => new Date(), []);

  const narrowDayFormatter = useMemo(
    () => new Intl.DateTimeFormat(intlLocale, { weekday: "narrow" }),
    [intlLocale],
  );

  // The WeekDayBar is only rendered for `timeGridDay` (where it doubles
  // as a day picker) and `listWeek` (where it anchors today). Other
  // mobile views use the library's native column headers instead.
  const isSelected = (date: Date): boolean => {
    if (currentView === "timeGridDay") {
      return isSameDay(date, currentDate);
    }
    if (currentView === "listWeek") {
      return isSameDay(date, today);
    }
    return false;
  };

  const handleClick = (date: Date) => {
    if (currentView !== "listWeek") {
      onDayClick(date);
    }
  };

  return (
    <div className="week-day-bar">
      <div className="week-day-bar__names">
        {weekDays.map((date) => (
          <span
            key={date.toISOString()}
            className={`week-day-bar__day-name${isWeekend(date) ? " week-day-bar__day-name--weekend" : ""}`}
          >
            {narrowDayFormatter.format(date)}
          </span>
        ))}
      </div>
      <div className="week-day-bar__numbers">
        {weekDays.map((date) => {
          const classes = [
            "week-day-bar__number",
            isSelected(date) && "week-day-bar__number--selected",
            isWeekend(date) && "week-day-bar__number--weekend",
          ]
            .filter(Boolean)
            .join(" ");

          return (
            <button
              key={date.toISOString()}
              className={classes}
              onClick={() => handleClick(date)}
              type="button"
            >
              {date.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
};
