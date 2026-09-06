/**
 * Color palette offered when creating/editing a calendar.
 */
export const DEFAULT_COLORS = [
  "#3788d8", // Blue
  "#28a745", // Green
  "#dc3545", // Red
  "#ffc107", // Yellow
  "#6f42c1", // Purple
  "#fd7e14", // Orange
  "#20c997", // Teal
  "#e83e8c", // Pink
];

/**
 * Fallback color for calendars/events that carry no explicit color:
 * the first palette entry, so the grid, the mobile list, the calendar
 * list and the color picker all agree.
 */
export const DEFAULT_EVENT_COLOR = DEFAULT_COLORS[0];
