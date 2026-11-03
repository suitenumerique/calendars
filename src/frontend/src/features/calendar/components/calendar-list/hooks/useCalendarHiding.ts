import { useCallback } from "react";

import type { CalendarContextType } from "../../../contexts/CalendarContext";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";

interface UseCalendarHidingProps {
  setCalendarHidden: CalendarContextType["setCalendarHidden"];
  /** Reports a failure. `hidden` is the value that the user asked for. */
  onError: (hidden: boolean) => void;
}

/**
 * Hides a calendar for the user, or shows it again (see
 * `CalDavCalendar.hidden`). Each action resolves to true when the server
 * accepts the change.
 */
export const useCalendarHiding = ({ setCalendarHidden, onError }: UseCalendarHidingProps) => {
  const setHidden = useCallback(
    async (calendar: CalDavCalendar, hidden: boolean) => {
      const { success, error } = await setCalendarHidden(calendar.url, hidden);
      if (!success) {
        console.error("Failed to change the hidden state of a calendar:", error);
        onError(hidden);
      }
      return success;
    },
    [setCalendarHidden, onError],
  );

  const hide = useCallback((calendar: CalDavCalendar) => setHidden(calendar, true), [setHidden]);
  const show = useCallback((calendar: CalDavCalendar) => setHidden(calendar, false), [setHidden]);

  return { hide, show, setHidden };
};
