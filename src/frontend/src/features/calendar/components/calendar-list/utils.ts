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

/**
 * Returns the emails to share with: each person once (case-insensitive),
 * without the owner. The server fails with an unclear error when a sharee
 * is the owner, and a duplicate recipient can cause an insert failure.
 * ShareModal from ui-components compares selected users by ID, so a
 * directory user and an email-only entry can have the same email.
 * See issue #140 for the server-side fix.
 */
export const getShareeEmails = (users: { email: string }[], owner: string | undefined): string[] =>
  users
    .filter((user, index) => {
      const key = user.email.toLowerCase();
      // Keep the first user with this email.
      return key !== owner && users.findIndex((u) => u.email.toLowerCase() === key) === index;
    })
    .map((user) => user.email);

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

/** The delete entry of a calendar menu, before translation. */
export interface DeleteMenuEntry {
  labelKey: string;
  callback?: () => void;
}

/**
 * Returns the delete entry of a calendar menu. The delete for every mailbox
 * user replaces the ordinary delete and leave actions. A sync-managed
 * calendar has no entry for other users: they hide it instead.
 */
export const getDeleteMenuEntry = ({
  onDelete,
  onLeave,
  syncManaged,
  onDeleteForMailbox,
}: {
  onDelete?: () => void;
  onLeave?: () => void;
  syncManaged?: boolean;
  onDeleteForMailbox?: () => void;
}): DeleteMenuEntry | null => {
  if (onDeleteForMailbox) {
    return { labelKey: "calendar.list.deleteForMailbox", callback: onDeleteForMailbox };
  }
  if (syncManaged) return null;
  return {
    labelKey: onLeave ? "calendar.list.leaveCalendar" : "calendar.list.delete",
    callback: onLeave ?? onDelete,
  };
};
