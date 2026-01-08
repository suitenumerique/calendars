/**
 * Simple wrapper around useEventModal for the "Créer" button.
 */

import { useMemo } from "react";
import type { IcsEvent } from 'ts-ics';
import { useEventModal, apiCalendarToOpenCalendar } from './useEventModal';
import { Calendar as ApiCalendar } from '../api';

interface UseCreateEventModalProps {
  calendars?: ApiCalendar[] | null;
  selectedDate?: Date;
}

export const useCreateEventModal = ({ calendars, selectedDate }: UseCreateEventModalProps) => {
  const openCalendars = useMemo(() => {
    if (!Array.isArray(calendars)) return [];
    return calendars.map(apiCalendarToOpenCalendar);
  }, [calendars]);
  
  const initialEvent = useMemo((): IcsEvent | null => {
    if (!selectedDate) return null;
    const start = new Date(selectedDate);
    start.setHours(9, 0, 0, 0);
    const end = new Date(start);
    end.setHours(10, 0, 0, 0);
    return {
      uid: `event-${Date.now()}`,
      summary: '',
      start: { type: 'DATE-TIME', date: start, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
      end: { type: 'DATE-TIME', date: end, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
    };
  }, [selectedDate]);

  const modal = useEventModal({
    calendars: openCalendars,
    initialEvent,
    initialCalendarUrl: Array.isArray(calendars) && calendars[0]?.id ? calendars[0].id : '',
  });

  return {
    ...modal,
    open: () => modal.open(initialEvent, 'create', Array.isArray(calendars) && calendars[0]?.id ? calendars[0].id : ''),
  };
};
