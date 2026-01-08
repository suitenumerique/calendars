/**
 * Unified hook for managing EventModal state.
 * Can be used both in React components and adapted for open-calendar.
 */

import { useState, useMemo, useCallback, useEffect } from "react";
import type { IcsEvent } from 'ts-ics';
import { EventModal } from '../components/EventModal';
import { Calendar as ApiCalendar } from '../api';

// Re-export Calendar type from EventModal for consistency
export type { Calendar as OpenCalendar } from '../components/EventModal';

// Convert API Calendar to open-calendar Calendar format  
export function apiCalendarToOpenCalendar(cal: ApiCalendar): OpenCalendar {
  return {
    url: cal.id,
    uid: cal.id,
    displayName: cal.name,
    calendarColor: cal.color,
    description: cal.description,
  };
}


interface UseEventModalProps {
  calendars?: OpenCalendar[];
  initialEvent?: IcsEvent | null;
  initialCalendarUrl?: string;
  onSubmit?: (event: IcsEvent, calendarUrl: string) => Promise<void>;
  onDelete?: (event: IcsEvent, calendarUrl: string) => Promise<void>;
}

export const useEventModal = ({
  calendars,
  initialEvent = null,
  initialCalendarUrl = '',
  onSubmit: customOnSubmit,
  onDelete: customOnDelete,
}: UseEventModalProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [mode, setMode] = useState<'create' | 'edit'>('create');
  const [event, setEvent] = useState<IcsEvent | null>(initialEvent);
  const [currentCalendars, setCurrentCalendars] = useState<OpenCalendar[]>(calendars || []);
  const [calendarUrl, setCalendarUrl] = useState<string>(initialCalendarUrl || calendars[0]?.url || '');
  const [allDay, setAllDay] = useState(false);
  
  // Update calendars when they change
  useEffect(() => {
    if (calendars && calendars.length > 0) {
      setCurrentCalendars(calendars);
    }
  }, [calendars]);

  const handleSubmit = useCallback(async (event: IcsEvent, calendarUrl: string) => {
    if (customOnSubmit) {
      await customOnSubmit(event, calendarUrl);
    }
    setIsOpen(false);
  }, [customOnSubmit]);

  const handleDelete = useCallback(async (event: IcsEvent, calendarUrl: string) => {
    if (customOnDelete) {
      await customOnDelete(event, calendarUrl);
    }
    setIsOpen(false);
  }, [customOnDelete]);

  const open = useCallback((event?: IcsEvent | null, mode: 'create' | 'edit' = 'create', calendarUrl?: string, calendars?: OpenCalendar[]) => {
    setEvent(event || null);
    setMode(mode);
    if (calendarUrl !== undefined) setCalendarUrl(calendarUrl);
    if (calendars && calendars.length > 0) setCurrentCalendars(calendars);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  return {
    isOpen,
    mode,
    event,
    calendarUrl,
    open,
    close,
    Modal: (
      <EventModal
        isOpen={isOpen}
        mode={mode}
        calendars={currentCalendars}
        selectedEvent={event}
        calendarUrl={calendarUrl}
        onSubmit={handleSubmit}
        onAllDayChange={setAllDay}
        onClose={close}
        onDelete={mode === 'edit' ? handleDelete : undefined}
      />
    ),
  };
};
