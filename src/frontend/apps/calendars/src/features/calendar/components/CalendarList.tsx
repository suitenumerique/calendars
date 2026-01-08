/**
 * CalendarList component - List of calendars with visibility toggles.
 */

import { Button, Checkbox } from "@openfun/cunningham-react";

import { Calendar } from "../api";
import { useToggleCalendarVisibility } from "../hooks/useCalendars";

interface CalendarListProps {
  calendars: Calendar[];
  onCreateCalendar: () => void;
}

export const CalendarList = ({
  calendars,
  onCreateCalendar,
}: CalendarListProps) => {
  const toggleVisibility = useToggleCalendarVisibility();

  // Ensure calendars is an array
  const calendarsArray = Array.isArray(calendars) ? calendars : [];

  const ownedCalendars = calendarsArray.filter(
    (cal) => !cal.name.includes("(partagé)")
  );
  const sharedCalendars = calendarsArray.filter((cal) =>
    cal.name.includes("(partagé)")
  );

  const handleToggle = (calendarId: string) => {
    toggleVisibility.mutate(calendarId);
  };

  const renderCalendarItem = (calendar: Calendar) => (
    <div key={calendar.id} className="calendar-list__item">
      <Checkbox
        checked={calendar.is_visible}
        onChange={() => handleToggle(calendar.id)}
        label=""
        aria-label={`Afficher ${calendar.name}`}
      />
      <span
        className="calendar-list__color"
        style={{ backgroundColor: calendar.color }}
      />
      <span className="calendar-list__name" title={calendar.name}>
        {calendar.name}
      </span>
      {calendar.is_default && (
        <span className="calendar-list__badge">Par défaut</span>
      )}
    </div>
  );

  return (
    <div className="calendar-list">
      <div className="calendar-list__section">
        <div className="calendar-list__section-header">
          <span className="calendar-list__section-title">Mes calendriers</span>
          <button
            className="calendar-list__add-btn"
            onClick={onCreateCalendar}
            title="Créer un calendrier"
          >
            <span className="material-icons">add</span>
          </button>
        </div>
        <div className="calendar-list__items">
          {ownedCalendars.map(renderCalendarItem)}
        </div>
      </div>

      {sharedCalendars.length > 0 && (
        <div className="calendar-list__section">
          <div className="calendar-list__section-header">
            <span className="calendar-list__section-title">
              Calendriers partagés
            </span>
          </div>
          <div className="calendar-list__items">
            {sharedCalendars.map(renderCalendarItem)}
          </div>
        </div>
      )}
    </div>
  );
};
