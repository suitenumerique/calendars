import { useCallback } from "react";

import type { CalendarContextType } from "../../../contexts/CalendarContext";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";
import { useCalendarAction } from "./useCalendarAction";

interface UseMailboxCalendarDeleteProps {
  deleteMailboxCalendar: CalendarContextType["deleteMailboxCalendar"];
  onError: () => void;
}

/** Tracks the mailbox calendar that an admin deletes for every mailbox user. */
export const useMailboxCalendarDelete = ({
  deleteMailboxCalendar,
  onError,
}: UseMailboxCalendarDeleteProps) => {
  const run = useCallback(
    (calendar: CalDavCalendar) =>
      calendar.mailboxEmail ? deleteMailboxCalendar(calendar.url, calendar.mailboxEmail) : null,
    [deleteMailboxCalendar],
  );
  return useCalendarAction({ run, errorMessage: "Failed to delete mailbox calendar:", onError });
};
