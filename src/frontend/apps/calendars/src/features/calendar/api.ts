/**
 * API functions for calendar operations.
 */

import { fetchAPI, fetchAPIFormData } from "@/features/api/fetchApi";

export interface Calendar {
  id: string;
  name: string;
  color: string;
  description: string;
  is_default: boolean;
  is_visible: boolean;
  caldav_path: string;
  owner: string;
}


/**
 * Paginated API response.
 */
interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/**
 * Fetch all calendars accessible by the current user.
 */
export const getCalendars = async (): Promise<Calendar[]> => {
  const response = await fetchAPI("calendars/");
  const data: PaginatedResponse<Calendar> = await response.json();
  return data.results;
};

/**
 * Create a new calendar via Django API.
 * This creates both the CalDAV calendar and the Django record.
 */
export const createCalendarApi = async (data: {
  name: string;
  color?: string;
  description?: string;
}): Promise<Calendar> => {
  const response = await fetchAPI("calendars/", {
    method: "POST",
    body: JSON.stringify(data),
  });
  return response.json();
};

/**
 * Update an existing calendar via Django API.
 */
export const updateCalendarApi = async (
  calendarId: string,
  data: { name?: string; color?: string; description?: string }
): Promise<Calendar> => {
  const response = await fetchAPI(`calendars/${calendarId}/`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  return response.json();
};

/**
 * Delete a calendar via Django API.
 */
export const deleteCalendarApi = async (calendarId: string): Promise<void> => {
  await fetchAPI(`calendars/${calendarId}/`, {
    method: "DELETE",
  });
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

/**
 * Subscription token for iCal export.
 */
export interface SubscriptionToken {
  token: string;
  url: string;
  caldav_path: string;
  calendar_name: string;
  is_active: boolean;
  last_accessed_at: string | null;
  created_at: string;
}

/**
 * Parameters for subscription token operations.
 */
export interface SubscriptionTokenParams {
  caldavPath: string;
  calendarName?: string;
}

/**
 * Error types for subscription token operations.
 */
export type SubscriptionTokenError =
  | { type: "not_found" }
  | { type: "permission_denied"; message: string }
  | { type: "network_error"; message: string }
  | { type: "server_error"; message: string };

/**
 * Result type for getSubscriptionToken - either a token, null (not found), or an error.
 */
export type GetSubscriptionTokenResult =
  | { success: true; token: SubscriptionToken | null }
  | { success: false; error: SubscriptionTokenError };

/**
 * Get the subscription token for a calendar by CalDAV path.
 * Returns a result object with either the token (or null if not found) or an error.
 */
export const getSubscriptionToken = async (
  caldavPath: string
): Promise<GetSubscriptionTokenResult> => {
  try {
    const response = await fetchAPI(
      `subscription-tokens/by-path/?caldav_path=${encodeURIComponent(caldavPath)}`,
      { method: "GET" }
    );
    return { success: true, token: await response.json() };
  } catch (error) {
    if (error && typeof error === "object" && "status" in error) {
      const status = error.status as number;
      // 404 means no token exists yet - this is expected
      if (status === 404) {
        return { success: true, token: null };
      }
      // Permission denied
      if (status === 403) {
        return {
          success: false,
          error: {
            type: "permission_denied",
            message: "You don't have access to this calendar",
          },
        };
      }
      // Server error
      if (status >= 500) {
        return {
          success: false,
          error: {
            type: "server_error",
            message: "Server error. Please try again later.",
          },
        };
      }
    }
    // Network or unknown error
    return {
      success: false,
      error: {
        type: "network_error",
        message: "Network error. Please check your connection.",
      },
    };
  }
};

/**
 * Create or get existing subscription token for a calendar.
 */
export const createSubscriptionToken = async (
  params: SubscriptionTokenParams
): Promise<SubscriptionToken> => {
  const response = await fetchAPI("subscription-tokens/", {
    method: "POST",
    body: JSON.stringify({
      caldav_path: params.caldavPath,
      calendar_name: params.calendarName || "",
    }),
  });
  return response.json();
};

/**
 * Delete (revoke) the subscription token for a calendar.
 */
export const deleteSubscriptionToken = async (
  caldavPath: string
): Promise<void> => {
  await fetchAPI(
    `subscription-tokens/by-path/?caldav_path=${encodeURIComponent(caldavPath)}`,
    {
      method: "DELETE",
    }
  );
};

/**
 * Result of an ICS import operation.
 */
export interface ImportEventsResult {
  total_events: number;
  imported_count: number;
  duplicate_count: number;
  skipped_count: number;
  errors?: string[];
}

/**
 * Import events from an ICS file into a calendar.
 */
export const importEventsApi = async (
  calendarId: string,
  file: File,
): Promise<ImportEventsResult> => {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetchAPIFormData(
    `calendars/${calendarId}/import_events/`,
    {
      method: "POST",
      body: formData,
    },
  );
  return response.json();
};

