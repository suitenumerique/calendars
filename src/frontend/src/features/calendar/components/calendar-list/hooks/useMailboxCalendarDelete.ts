import { useState, useCallback } from "react";

import type { CalendarContextType } from "../../../contexts/CalendarContext";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";

interface UseMailboxCalendarDeleteProps {
  deleteMailboxCalendar: CalendarContextType["deleteMailboxCalendar"];
  onError: () => void;
}

/**
 * Tracks the selected calendar and the delete progress, and reports a failed
 * delete. The calendar stays selected until the delete settles.
 */
export const useMailboxCalendarDelete = ({
  deleteMailboxCalendar,
  onError,
}: UseMailboxCalendarDeleteProps) => {
  const [calendar, setCalendar] = useState<CalDavCalendar | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const open = useCallback((target: CalDavCalendar) => setCalendar(target), []);

  const close = useCallback(() => {
    if (isLoading) return;
    setCalendar(null);
  }, [isLoading]);

  const confirm = useCallback(async () => {
    if (!calendar?.mailboxEmail) return;

    setIsLoading(true);
    let success = false;
    try {
      ({ success } = await deleteMailboxCalendar(calendar.url, calendar.mailboxEmail));
    } catch (error) {
      console.error("Failed to delete mailbox calendar:", error);
    } finally {
      setIsLoading(false);
      setCalendar(null);
    }
    if (!success) onError();
  }, [calendar, deleteMailboxCalendar, onError]);

  return { calendar, isLoading, open, close, confirm };
};
