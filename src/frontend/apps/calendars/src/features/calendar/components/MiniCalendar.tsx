/**
 * MiniCalendar component - A small month calendar for date navigation.
 */

import { useMemo, useState } from "react";

import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  startOfMonth,
  startOfWeek,
  subMonths,
} from "date-fns";
import { fr } from "date-fns/locale";

interface MiniCalendarProps {
  selectedDate: Date;
  onDateSelect: (date: Date) => void;
}

export const MiniCalendar = ({
  selectedDate,
  onDateSelect,
}: MiniCalendarProps) => {
  const [viewDate, setViewDate] = useState(selectedDate);

  const days = useMemo(() => {
    const monthStart = startOfMonth(viewDate);
    const monthEnd = endOfMonth(viewDate);
    const calendarStart = startOfWeek(monthStart, { weekStartsOn: 1 });
    const calendarEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });

    return eachDayOfInterval({ start: calendarStart, end: calendarEnd });
  }, [viewDate]);

  const weekDays = ["L", "M", "M", "J", "V", "S", "D"];

  const handlePrevMonth = () => {
    setViewDate(subMonths(viewDate, 1));
  };

  const handleNextMonth = () => {
    setViewDate(addMonths(viewDate, 1));
  };

  const handleDayClick = (day: Date) => {
    onDateSelect(day);
  };

  return (
    <div className="mini-calendar">
      <div className="mini-calendar__header">
        <button
          className="mini-calendar__nav-btn"
          onClick={handlePrevMonth}
          aria-label="Mois précédent"
        >
          <span className="material-icons">chevron_left</span>
        </button>
        <span className="mini-calendar__month-title">
          {format(viewDate, "MMMM yyyy", { locale: fr })}
        </span>
        <button
          className="mini-calendar__nav-btn"
          onClick={handleNextMonth}
          aria-label="Mois suivant"
        >
          <span className="material-icons">chevron_right</span>
        </button>
      </div>

      <div className="mini-calendar__weekdays">
        {weekDays.map((day, index) => (
          <div key={index} className="mini-calendar__weekday">
            {day}
          </div>
        ))}
      </div>

      <div className="mini-calendar__days">
        {days.map((day, index) => {
          const isCurrentMonth = isSameMonth(day, viewDate);
          const isSelected = isSameDay(day, selectedDate);
          const isToday = isSameDay(day, new Date());

          return (
            <button
              key={index}
              className={`mini-calendar__day ${
                !isCurrentMonth ? "mini-calendar__day--outside" : ""
              } ${isSelected ? "mini-calendar__day--selected" : ""} ${
                isToday ? "mini-calendar__day--today" : ""
              }`}
              onClick={() => handleDayClick(day)}
            >
              {format(day, "d")}
            </button>
          );
        })}
      </div>
    </div>
  );
};
