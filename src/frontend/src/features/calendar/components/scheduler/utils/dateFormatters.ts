/**
 * Date formatting utilities for the Scheduler components.
 * Handles conversion between Date objects and HTML input formats.
 */

/**
 * Pad a number with leading zeros to `width` digits.
 */
const pad = (n: number, width = 2): string => n.toString().padStart(width, "0");

/**
 * Build a local Date. Unlike the Date constructor, it keeps years below 100
 * as they are, so year 2 stays year 2 and does not become 1902.
 */
const localDate = (
  year: number,
  monthIndex: number,
  day: number,
  hours = 0,
  minutes = 0,
  seconds = 0,
  ms = 0,
): Date => {
  // Set the date before the time, so that a DST change on the same day of
  // another year has no effect on the time.
  const date = new Date(2000, 0, 1);
  date.setFullYear(year, monthIndex, day);
  date.setHours(hours, minutes, seconds, ms);
  return date;
};

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
    return `${pad(date.getUTCFullYear(), 4)}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  }
  return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

/**
 * Parse a datetime-local input value to a Date in local time.
 *
 * Parses datetime-local values as local date and time components,
 * with optional seconds and fractional seconds. Other input formats go
 * to the Date constructor.
 *
 * @param value - String in YYYY-MM-DDTHH:mm[:ss[.sss]] format
 */
export const parseDateTimeLocal = (value: string): Date => {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/);
  if (match) {
    const [, y, mo, d, h, mi, s, ms] = match;
    return localDate(
      Number(y),
      Number(mo) - 1,
      Number(d),
      Number(h),
      Number(mi),
      s ? Number(s) : 0,
      ms ? Number(ms.padEnd(3, "0").slice(0, 3)) : 0,
    );
  }
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
    return `${pad(date.getUTCFullYear(), 4)}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
  }
  return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};

/**
 * Parse date input value to Date (at midnight local time).
 *
 * @param value - String in YYYY-MM-DD format
 */
export const parseDateLocal = (value: string): Date => {
  const [year, month, day] = value.split("-").map(Number);
  return localDate(year, month - 1, day);
};
