/**
 * Utilities for the values of the date and datetime-local inputs.
 * They convert between Date objects and input values, and change these values.
 */

import { addDays } from "@/utils/date";

/**
 * Pad a number with leading zeros to `width` digits.
 */
const pad = (n: number, width = 2): string => n.toString().padStart(width, "0");

/**
 * Build a local Date. The numeric Date constructor changes the years 0 to 99
 * to 1900 to 1999. This function keeps the year, so year 2 stays year 2.
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
  // For "fake UTC" dates, getUTC* methods return the intended local time
  const hours = isFakeUtc ? date.getUTCHours() : date.getHours();
  const minutes = isFakeUtc ? date.getUTCMinutes() : date.getMinutes();
  return `${formatDateLocal(date, isFakeUtc)}T${pad(hours)}:${pad(minutes)}`;
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

const DAY_MS = 24 * 60 * 60 * 1000;

const isValid = (date: Date): boolean => !Number.isNaN(date.getTime());

/**
 * Tell if the parse of an input value gives a valid timestamp.
 * The value can be incomplete. For example, "2026" is valid for a
 * datetime-local input.
 */
export const isValidDateInput = (value: string, isAllDay: boolean): boolean =>
  isValid(isAllDay ? parseDateLocal(value) : parseDateTimeLocal(value));

/**
 * Move the end so that the event keeps its duration when the start changes.
 * An all-day event keeps its number of calendar days, so a DST change does
 * not add or remove a day.
 * Return the previous end unchanged if one of the values is not a valid date,
 * for example a partial value while the user types.
 */
export const shiftEnd = (
  prevStart: string,
  prevEnd: string,
  nextStart: string,
  isAllDay: boolean,
): string => {
  const parse = isAllDay ? parseDateLocal : parseDateTimeLocal;
  const oldStart = parse(prevStart);
  const oldEnd = parse(prevEnd);
  const newStart = parse(nextStart);
  if (!isValid(oldStart) || !isValid(oldEnd) || !isValid(newStart)) {
    return prevEnd;
  }
  if (!isAllDay) {
    return formatDateTimeLocal(
      new Date(newStart.getTime() + oldEnd.getTime() - oldStart.getTime()),
    );
  }
  // A DST change alters the time between two local midnights.
  // Rounding gives the number of calendar days.
  const days = Math.round((oldEnd.getTime() - oldStart.getTime()) / DAY_MS);
  return formatDateLocal(addDays(newStart, days));
};
