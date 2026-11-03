import type { CalDavService } from "../services/dav/CalDavService";

/**
 * Writes the hidden state of a calendar, then refreshes the calendars.
 * Success means that the server accepted the write. It does not mean that
 * the list shows the new state: `refresh` reports its own failures and
 * keeps the calendars of the last fetch.
 */
export const setCalendarHiddenAndRefresh = async (
  caldavService: Pick<CalDavService, "setCalendarHidden">,
  refresh: () => Promise<void>,
  calendarUrl: string,
  hidden: boolean,
): Promise<{ success: boolean; error?: string }> => {
  try {
    const result = await caldavService.setCalendarHidden(calendarUrl, hidden);
    if (!result.success) {
      return { success: false, error: result.error || "Failed to update calendar" };
    }
    await refresh();
    return { success: true };
  } catch (error) {
    console.error("Error hiding calendar:", error);
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
};
