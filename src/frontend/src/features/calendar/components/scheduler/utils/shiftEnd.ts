import {
  formatDateLocal,
  formatDateTimeLocal,
  parseDateLocal,
  parseDateTimeLocal,
} from "./dateFormatters";

const isValid = (date: Date): boolean => !Number.isNaN(date.getTime());

/**
 * Move the end so that the event keeps its duration when the start changes.
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
  const format = isAllDay ? formatDateLocal : formatDateTimeLocal;
  const oldStart = parse(prevStart);
  const oldEnd = parse(prevEnd);
  const newStart = parse(nextStart);
  if (!isValid(oldStart) || !isValid(oldEnd) || !isValid(newStart)) {
    return prevEnd;
  }
  return format(new Date(newStart.getTime() + oldEnd.getTime() - oldStart.getTime()));
};
