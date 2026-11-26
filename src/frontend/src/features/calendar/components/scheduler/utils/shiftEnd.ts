import {
  formatDateLocal,
  formatDateTimeLocal,
  parseDateLocal,
  parseDateTimeLocal,
} from "./dateFormatters";

const DAY_MS = 24 * 60 * 60 * 1000;

const isValid = (date: Date): boolean => !Number.isNaN(date.getTime());

/**
 * Tell if a value of the start or end input is a complete, valid date.
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
  // A DST change makes a day 23 or 25 hours long. Rounding gives the number
  // of calendar days.
  const days = Math.round((oldEnd.getTime() - oldStart.getTime()) / DAY_MS);
  newStart.setDate(newStart.getDate() + days);
  return formatDateLocal(newStart);
};
