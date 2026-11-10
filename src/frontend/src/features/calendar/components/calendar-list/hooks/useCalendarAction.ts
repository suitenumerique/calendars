import { useState, useCallback } from "react";

import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";

interface UseCalendarActionProps {
  /** The request for the selected calendar. Null when the calendar lacks the data for it. */
  run: (calendar: CalDavCalendar) => Promise<{ success: boolean }> | null;
  /** The console message of a failed request. */
  errorMessage: string;
  onError: () => void;
}

/**
 * Tracks the calendar that the user selected for a request and the
 * progress of the request. The calendar stays selected until the
 * request settles.
 */
export const useCalendarAction = ({ run, errorMessage, onError }: UseCalendarActionProps) => {
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
      const request = run(calendar);
      if (!request) return;
      ({ success } = await request);
    } catch (error) {
      console.error(errorMessage, error);
    } finally {
      setIsLoading(false);
      setCalendar(null);
    }
    if (!success) onError();
  }, [calendar, run, errorMessage, onError]);

  return { calendar, isLoading, open, close, confirm };
};
