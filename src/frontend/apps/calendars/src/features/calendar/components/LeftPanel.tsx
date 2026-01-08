/**
 * LeftPanel component - Calendar sidebar with mini calendar and calendar list.
 */

import { useState } from "react";

import { Button } from "@openfun/cunningham-react";

import { Calendar } from "../api";
import { CalendarList } from "./CalendarList";
import { MiniCalendar } from "./MiniCalendar";

interface LeftPanelProps {
  calendars: Calendar[];
  selectedDate: Date;
  onDateSelect: (date: Date) => void;
  onCreateEvent: () => void;
  onCreateCalendar: () => void;
}

export const LeftPanel = ({
  calendars,
  selectedDate,
  onDateSelect,
  onCreateEvent,
  onCreateCalendar,
}: LeftPanelProps) => {
  return (
    <div className="calendar-left-panel">
      <div className="calendar-left-panel__create">
        <Button onClick={onCreateEvent} icon={<span className="material-icons">add</span>}>
          Créer
        </Button>
      </div>

      <MiniCalendar selectedDate={selectedDate} onDateSelect={onDateSelect} />

      <div className="calendar-left-panel__divider" />

      <CalendarList calendars={calendars} onCreateCalendar={onCreateCalendar} />
    </div>
  );
};
