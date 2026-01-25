/**
 * MiniCalendar component - A small month calendar for date navigation.
 */

import { useEffect, useMemo, useState } from "react";

import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  getWeek,
  isSameDay,
  isSameMonth,
  startOfMonth,
  startOfWeek,
  subMonths,
} from "date-fns";
import { fr } from "date-fns/locale";
import { useTranslation } from "react-i18next";
import { useCalendarContext } from "../contexts";

interface MiniCalendarProps {
  selectedDate: Date;
  onDateSelect: (date: Date) => void;
}

// Helper to chunk array into groups of n
const chunkArray = <T,>(arr: T[], size: number): T[][] => {
  const result: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    result.push(arr.slice(i, i + size));
  }
  return result;
};

export const MiniCalendar = ({
  selectedDate,
  onDateSelect,
}: MiniCalendarProps) => {
  const { t } = useTranslation();
  const { goToDate, currentDate } = useCalendarContext();
  const [viewDate, setViewDate] = useState(selectedDate);

  // Sync viewDate when main calendar navigates (via prev/next buttons)
  useEffect(() => {
    setViewDate((prevViewDate) => {
      // Only update if the month changed to avoid unnecessary re-renders
      if (!isSameMonth(prevViewDate, currentDate)) {
        return currentDate;
      }
      return prevViewDate;
    });
  }, [currentDate]);

  const days = useMemo(() => {
    const monthStart = startOfMonth(viewDate);
    const monthEnd = endOfMonth(viewDate);
    const calendarStart = startOfWeek(monthStart, { weekStartsOn: 1 });
    const calendarEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });

    return eachDayOfInterval({ start: calendarStart, end: calendarEnd });
  }, [viewDate]);

  // Group days by weeks
  const weeks = useMemo(() => chunkArray(days, 7), [days]);

  const weekDays = ["lu", "ma", "me", "je", "ve", "sa", "di"];

  const handlePrevMonth = () => {
    setViewDate(subMonths(viewDate, 1));
  };

  const handleNextMonth = () => {
    setViewDate(addMonths(viewDate, 1));
  };

  const handleDayClick = (day: Date) => {
    onDateSelect(day);
    goToDate(day);
  };

  return (
    <div className="mini-calendar">
      <div className="mini-calendar__header">
        <span className="mini-calendar__month-title">
          {format(viewDate, "MMMM yyyy", { locale: fr })}
        </span>
        <div className="mini-calendar__nav">
          <button
            className="mini-calendar__nav-btn"
            onClick={handlePrevMonth}
            aria-label={t("calendar.miniCalendar.previousMonth")}
          >
            <span className="material-icons">chevron_left</span>
          </button>
          <button
            className="mini-calendar__nav-btn"
            onClick={handleNextMonth}
            aria-label={t("calendar.miniCalendar.nextMonth")}
          >
            <span className="material-icons">chevron_right</span>
          </button>
        </div>
      </div>

      <div className="mini-calendar__grid">
        {/* Header row with week number column and days */}
        <div className="mini-calendar__weekdays">
          <div className="mini-calendar__weekday mini-calendar__weekday--week-num">
            Sem.
          </div>
          {weekDays.map((day, index) => (
            <div key={index} className="mini-calendar__weekday">
              {day}
            </div>
          ))}
        </div>

        {/* Calendar body with weeks */}
        <div className="mini-calendar__body">
          {weeks.map((week, weekIndex) => {
            const weekNumber = getWeek(week[0], { weekStartsOn: 1 });
            return (
              <div key={weekIndex} className="mini-calendar__week">
                <div className="mini-calendar__week-number">{weekNumber}</div>
                {week.map((day, dayIndex) => {
                  const isCurrentMonth = isSameMonth(day, viewDate);
                  const isSelected = isSameDay(day, selectedDate);
                  const isToday = isSameDay(day, new Date());

                  return (
                    <button
                      key={dayIndex}
                      className={`mini-calendar__day ${
                        !isCurrentMonth ? "mini-calendar__day--outside" : ""
                      } ${isSelected ? "mini-calendar__day--selected" : ""} ${
                        isToday && !isSelected ? "mini-calendar__day--today" : ""
                      }`}
                      onClick={() => handleDayClick(day)}
                    >
                      {format(day, "d")}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
