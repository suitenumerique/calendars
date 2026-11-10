import { useState, useCallback } from "react";

import type { CalendarContextType } from "../../../contexts/CalendarContext";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";

interface UseCalendarDeleteProps {
  deleteCalendar: CalendarContextType["deleteCalendar"];
  onError: () => void;
}

/**
 * Tracks the calendar that the user deletes, or leaves as a sharee, and
 * the progress of the request. The calendar stays selected until the
 * request settles.
 */
export const useCalendarDelete = ({ deleteCalendar, onError }: UseCalendarDeleteProps) => {
  const [calendar, setCalendar] = useState<CalDavCalendar | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const open = useCallback((target: CalDavCalendar) => setCalendar(target), []);

  const close = useCallback(() => {
    if (isLoading) return;
    setCalendar(null);
  }, [isLoading]);

  const confirm = useCallback(async () => {
    if (!calendar) return;

    setIsLoading(true);
    let success = false;
    try {
      ({ success } = await deleteCalendar(calendar.url));
    } catch (error) {
      console.error("Failed to delete calendar:", error);
    } finally {
      setIsLoading(false);
      setCalendar(null);
    }
    if (!success) onError();
  }, [calendar, deleteCalendar, onError]);

  return { calendar, isLoading, open, close, confirm };
};
