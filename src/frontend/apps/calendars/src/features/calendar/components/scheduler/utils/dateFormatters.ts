/**
 * Date formatting utilities for the Scheduler components.
 * Handles conversion between Date objects and HTML input formats.
 */

/**
 * Pad a number to 2 digits.
 */
const pad = (n: number): string => n.toString().padStart(2, "0");

/**
 * Format Date to input datetime-local format (YYYY-MM-DDTHH:mm).
 *
 * @param date - The date to format
 * @param isFakeUtc - If true, use getUTC* methods (for dates from adapter
 *                    that store local time as UTC values)
 */
export const formatDateTimeLocal = (date: Date, isFakeUtc = false): string => {
  if (isFakeUtc) {
    // For "fake UTC" dates, getUTC* methods return the intended local time
    return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

/**
 * Parse datetime-local input value to Date.
 *
 * @param value - String in YYYY-MM-DDTHH:mm format
 */
export const parseDateTimeLocal = (value: string): Date => {
  return new Date(value);
};

/**
 * Format Date to input date format (YYYY-MM-DD).
 *
 * @param date - The date to format
 * @param isFakeUtc - If true, use getUTC* methods (for dates from adapter)
 */
export const formatDateLocal = (date: Date, isFakeUtc = false): string => {
  if (isFakeUtc) {
    return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};

/**
 * Parse date input value to Date (at midnight local time).
 *
 * @param value - String in YYYY-MM-DD format
 */
export const parseDateLocal = (value: string): Date => {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
};
