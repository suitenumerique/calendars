/**
 * API functions for calendar operations.
 */

import { fetchAPI } from "@/features/api/fetchApi";

export interface Calendar {
  id: string;
  name: string;
  color: string;
  description: string;
  is_default: boolean;
  is_visible: boolean;
  owner: string;
}


/**
 * Fetch all calendars accessible by the current user.
 */
export const getCalendars = async (): Promise<Calendar[]> => {
  const response = await fetchAPI("calendars/");
  return response.json();
};

/**
 * Create a new calendar.
 */
export const createCalendar = async (data: {
  name: string;
  color?: string;
}): Promise<Calendar> => {
  const response = await fetchAPI("calendars/", {
    method: "POST",
    body: JSON.stringify(data),
  });
  return response.json();
};

/**
 * Toggle calendar visibility.
 */
export const toggleCalendarVisibility = async (
  calendarId: string
): Promise<{ is_visible: boolean }> => {
  const response = await fetchAPI(`calendars/${calendarId}/toggle_visibility/`, {
    method: "PATCH",
  });
  return response.json();
};

