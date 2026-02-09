/**
 * Extract the CalDAV path from a full calendar URL.
 *
 * URL format: http://localhost:8921/api/v1.0/caldav/calendars/user@example.com/uuid/
 * Returns: /calendars/user@example.com/uuid/
 */
export const extractCaldavPath = (calendarUrl: string): string | null => {
  try {
    const url = new URL(calendarUrl);
    const pathParts = url.pathname.split("/").filter(Boolean);

    const calendarsIndex = pathParts.findIndex(
      (part) => part === "calendars",
    );

    if (calendarsIndex === -1) {
      console.error(
        "Invalid calendar URL format - 'calendars' segment not found:",
        calendarUrl,
      );
      return null;
    }

    const remainingParts = pathParts.slice(calendarsIndex);
    if (remainingParts.length < 3) {
      console.error(
        "Invalid calendar URL format - incomplete path:",
        calendarUrl,
      );
      return null;
    }

    return "/" + remainingParts.join("/") + "/";
  } catch (error) {
    console.error("Failed to parse calendar URL:", error);
    return null;
  }
};
