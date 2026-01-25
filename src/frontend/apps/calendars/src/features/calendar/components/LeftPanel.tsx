/**
 * LeftPanel component - Calendar sidebar with mini calendar and calendar list.
 */


import { Button } from "@gouvfr-lasuite/cunningham-react";

import { Calendar } from "../api";
import { CalendarList } from "./calendar-list";
import { MiniCalendar } from "./MiniCalendar";
import { useCalendarContext } from "../contexts";

interface LeftPanelProps {
  calendars: Calendar[];
  selectedDate: Date;
  onDateSelect: (date: Date) => void;
  onCreateEvent: () => void;
}

export const LeftPanel = ({
  calendars,
  selectedDate,
  onDateSelect,
  onCreateEvent,
}: LeftPanelProps) => {
  const { davCalendars } = useCalendarContext();
  console.log("davCalendars LeftPanel", davCalendars);
  return (
    <div className="calendar-left-panel">
      <div className="calendar-left-panel__create">
        <Button onClick={onCreateEvent} icon={<span className="material-icons">add</span>}>
          Créer
        </Button>
      </div>

      <MiniCalendar selectedDate={selectedDate} onDateSelect={onDateSelect} />

      <div className="calendar-left-panel__divider" />

      <CalendarList calendars={calendars} />
    </div>
  );
};
