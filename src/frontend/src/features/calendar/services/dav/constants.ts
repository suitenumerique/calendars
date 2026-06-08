export const attendeeRoleTypes = [
  "CHAIR",
  "REQ-PARTICIPANT",
  "OPT-PARTICIPANT",
  "NON-PARTICIPANT",
] as const;

export const availableViews = [
  "timeGridDay",
  "timeGridWeek",
  "dayGridMonth",
  "listDay",
  "listWeek",
  "listMonth",
  "listYear",
] as const;

/**
 * UI threshold for treating a recurrence as "no end date".
 *
 * Anything covering more than this many years — whether via an
 * `UNTIL` past today + N years, or via `COUNT × INTERVAL × FREQ`
 * exceeding N years from now — is rendered as "never" in the
 * recurrence editor. A user who created a "Daily forever" event
 * shouldn't see it re-classified as "ends after 7300 times" on
 * next edit just because the CalDAV sanitizer bounded it.
 *
 * Chosen below the server-side DAILY clamp window (~20 years) so
 * the UI and the sanitizer agree on what counts as effectively-
 * forever without the frontend having to hard-code the server's
 * per-FREQ cap values.
 */
export const FOREVER_YEARS_THRESHOLD = 15;
