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
 *
 * `new Date("2026-01-29T15:00")` is interpreted as local time but the
 * interpretation depends on the browser's current DST offset (see
 * src/frontend/test-dst.js). On Chromium 109 / old ICU the offset for
 * historical/future dates may be wrong by 1h (CET vs CEST). Parse
 * components explicitly to avoid that drift — construct via
 * `new Date(year, month-1, day, hours, minutes)` which is unambiguously
 * local time.
 */
export const parseDateTimeLocal = (value: string): Date => {
  // Fast path for the common datetime-local shape; fallback to Date parse
  // for any other ISO-like string (e.g. with seconds/millis).
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/);
  if (match) {
    const [, y, mo, d, h, mi, s, ms] = match;
    return new Date(
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
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
};
