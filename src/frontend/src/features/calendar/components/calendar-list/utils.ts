import { APIError } from "@/features/api/APIError";

/**
 * Extract the CalDAV path from a full calendar URL.
 *
 * URL format: http://localhost:8931/api/v1.0/caldav/calendars/user@example.com/uuid/
 * Returns: /calendars/user@example.com/uuid/
 */
export const extractCaldavPath = (calendarUrl: string): string | null => {
  try {
    const url = new URL(calendarUrl);
    const pathParts = url.pathname.split("/").filter(Boolean);

    const calendarsIndex = pathParts.findIndex((part) => part === "calendars");

    if (calendarsIndex === -1) {
      console.error("Invalid calendar URL format - 'calendars' segment not found:", calendarUrl);
      return null;
    }

    const remainingParts = pathParts.slice(calendarsIndex);
    if (remainingParts.length < 3) {
      console.error("Invalid calendar URL format - incomplete path:", calendarUrl);
      return null;
    }

    return "/" + remainingParts.join("/") + "/";
  } catch (error) {
    console.error("Failed to parse calendar URL:", error);
    return null;
  }
};

// Error code from the setup API: the user cannot send as the mailbox.
const MAILBOX_ROLE_REQUIRED = "mailbox_role_required";

/** Returns the translation key for an error that occurs when a calendar is saved. */
export const getCalendarSaveErrorKey = (error: unknown, mode: "create" | "edit"): string => {
  if (error instanceof APIError && error.data?.code === MAILBOX_ROLE_REQUIRED) {
    return "calendar.createCalendar.errorMailboxRole";
  }
  return mode === "create" ? "calendar.createCalendar.error" : "api.error.unexpected";
};

type ShareErrorResult = {
  error?: string;
  status?: number;
};

/** Translation key for a failed share. The two texts come from `MailboxPlugin.php`. */
export const getShareErrorKey = ({ error, status }: ShareErrorResult, fallbackKey: string) => {
  if (error?.includes("managed by Messages")) {
    return "calendar.shareCalendar.errorSyncManaged";
  }
  if (error?.includes("only be shared with read-only access")) {
    return "calendar.shareCalendar.errorMailboxReadOnly";
  }
  if (status === 403) {
    return "calendar.shareCalendar.errorForbidden";
  }
  return fallbackKey;
};

const ONBOARDING_DISMISSED_KEY = "calendar-onboarding-dismissed";

/**
 * Read the onboarding dismissal flag for this browser.
 * Return false when the flag is absent or storage is not available.
 */
export const loadOnboardingDismissed = (): boolean => {
  try {
    return localStorage.getItem(ONBOARDING_DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
};

export const saveOnboardingDismissed = () => {
  try {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, "1");
  } catch {
    // Ignore storage errors
  }
};
