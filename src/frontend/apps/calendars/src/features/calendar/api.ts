/**
 * API functions for calendar operations.
 */

import { APIError } from "@/features/api/APIError";
import { fetchAPI } from "@/features/api/fetchApi";

/**
 * Channel response from the API.
 */
export interface Channel {
  id: string;
  name: string;
  type: string;
  role: string;
  caldav_path: string;
  url: string | null;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
  settings: Record<string, unknown>;
}

/**
 * Channel with token (returned on creation).
 */
export interface ChannelWithToken extends Channel {
  token: string;
}

/**
 * Error types for channel operations.
 */
export type ChannelError =
  | { type: "not_found" }
  | { type: "permission_denied"; message: string }
  | { type: "network_error"; message: string }
  | { type: "server_error"; message: string };

/**
 * Result type for getICalFeedChannel.
 */
export type GetICalFeedResult =
  | { success: true; channel: Channel | null }
  | { success: false; error: ChannelError };

/**
 * Get the ical-feed channel for a calendar by CalDAV path.
 */
export const getICalFeedChannel = async (
  caldavPath: string,
): Promise<GetICalFeedResult> => {
  try {
    const response = await fetchAPI(
      `channels/?type=ical-feed`,
      { method: "GET" },
    );
    const channels: Channel[] = await response.json();
    const match = channels.find((c) => c.caldav_path === caldavPath) ?? null;
    return { success: true, channel: match };
  } catch (error) {
    if (error instanceof APIError) {
      const status = error.code;
      if (status === 403) {
        return {
          success: false,
          error: {
            type: "permission_denied",
            message: "You don't have access to this calendar",
          },
        };
      }
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
 * Create an ical-feed channel (get-or-create semantics on the backend).
 */
export const createICalFeedChannel = async (params: {
  caldavPath: string;
  calendarName?: string;
}): Promise<ChannelWithToken> => {
  const response = await fetchAPI("channels/", {
    method: "POST",
    body: JSON.stringify({
      name: params.calendarName || params.caldavPath,
      type: "ical-feed",
      caldav_path: params.caldavPath,
      calendar_name: params.calendarName || "",
    }),
  });
  return response.json();
};

/**
 * Delete a channel by ID.
 */
export const deleteChannel = async (channelId: string): Promise<void> => {
  await fetchAPI(`channels/${channelId}/`, {
    method: "DELETE",
  });
};

// ============================================================================
// Subscription Channel API
// ============================================================================

/**
 * Subscription channel response from the API.
 */
export interface SubscriptionChannel {
  id: string;
  name: string;
  type: "ical-subscription";
  caldav_path: string;
  is_active: boolean;
  source_url: string;
  last_sync_at: string | null;
  last_sync_status: "pending" | "ok" | "error" | "stopped";
  last_sync_error: string;
  error_count: number;
  sync_interval: number;
  created_at: string;
  updated_at: string;
}

/**
 * Get all subscription channels for the current user.
 */
export const getSubscriptionChannels = async (): Promise<
  SubscriptionChannel[]
> => {
  const response = await fetchAPI(`channels/?type=ical-subscription`, {
    method: "GET",
  });
  return response.json();
};

/**
 * Create a subscription channel.
 */
export const createSubscriptionChannel = async (params: {
  name: string;
  sourceUrl: string;
  color?: string;
}): Promise<SubscriptionChannel> => {
  const body: Record<string, string> = {
    name: params.name,
    type: "ical-subscription",
    source_url: params.sourceUrl,
  };
  if (params.color) {
    body.color = params.color;
  }
  const response = await fetchAPI("channels/", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return response.json();
};

/**
 * Update a subscription channel (name and/or source URL).
 */
export const updateSubscriptionChannel = async (
  channelId: string,
  params: { name?: string; sourceUrl?: string; color?: string },
): Promise<SubscriptionChannel> => {
  const body: Record<string, string> = {};
  if (params.name !== undefined) {
    body.name = params.name;
  }
  if (params.sourceUrl !== undefined) {
    body.source_url = params.sourceUrl;
  }
  if (params.color !== undefined) {
    body.color = params.color;
  }
  const response = await fetchAPI(`channels/${channelId}/`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  return response.json();
};

/**
 * Delete a subscription channel by ID.
 */
export const deleteSubscriptionChannel = async (
  channelId: string,
): Promise<void> => {
  await fetchAPI(`channels/${channelId}/`, {
    method: "DELETE",
  });
};

/**
 * Reactivate a stopped subscription channel.
 */
export const reactivateSubscriptionChannel = async (
  channelId: string,
): Promise<SubscriptionChannel> => {
  const response = await fetchAPI(`channels/${channelId}/reactivate/`, {
    method: "POST",
  });
  return response.json();
};

// ============================================================================
// ICS Import API
// ============================================================================

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
 * Response from the import-events endpoint (queued task).
 */
interface ImportTaskResponse {
  task_id: string;
}

/**
 * Task status response from the polling endpoint.
 */
export interface TaskStatus {
  status: "PENDING" | "PROGRESS" | "SUCCESS" | "FAILURE";
  result: ImportEventsResult | null;
  error: string | null;
  progress?: number;
  message?: string;
}

/**
 * Start an ICS import task. Returns the task_id for polling.
 */
export const startImportTask = async (
  caldavPath: string,
  file: File,
): Promise<string> => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("caldav_path", caldavPath);

  const response = await fetchAPI("calendars/import-events/", {
    method: "POST",
    body: formData,
  });
  const data: ImportTaskResponse = await response.json();
  return data.task_id;
};

/**
 * Poll the status of a task.
 */
export const getTaskStatus = async (taskId: string): Promise<TaskStatus> => {
  const response = await fetchAPI(`tasks/${taskId}/`, { method: "GET" });
  return response.json();
};

/**
 * Poll a task until it completes. Returns the import result.
 */
export const pollImportTask = async (
  taskId: string,
  onProgress?: (progress: number, message?: string) => void,
): Promise<ImportEventsResult> => {
  const POLL_INTERVAL = 1000; // 1 second

  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const status = await getTaskStatus(taskId);

        if (status.status === "PROGRESS") {
          onProgress?.(status.progress ?? 0, status.message);
          setTimeout(poll, POLL_INTERVAL);
          return;
        }

        if (status.status === "PENDING") {
          setTimeout(poll, POLL_INTERVAL);
          return;
        }

        if (status.status === "SUCCESS" && status.result) {
          resolve(status.result);
          return;
        }

        reject(
          new Error(
            status.error ?? "Import failed",
          ),
        );
      } catch (error) {
        reject(error);
      }
    };

    poll();
  });
};
