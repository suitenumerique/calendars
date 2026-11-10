import { useCallback } from "react";

import type { CalendarContextType } from "../../../contexts/CalendarContext";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";
import { useCalendarAction } from "./useCalendarAction";

interface UseCalendarDeleteProps {
  deleteCalendar: CalendarContextType["deleteCalendar"];
  onError: () => void;
}

/** Tracks the calendar that the user deletes, or leaves as a sharee. */
export const useCalendarDelete = ({ deleteCalendar, onError }: UseCalendarDeleteProps) => {
  const run = useCallback(
    (calendar: CalDavCalendar) => deleteCalendar(calendar.url),
    [deleteCalendar],
  );
  return useCalendarAction({ run, errorMessage: "Failed to delete calendar:", onError });
};
