import { generateIcsCalendar, type IcsCalendar } from "ts-ics";

const BARE_ABSOLUTE_TRIGGER = /^TRIGGER:(\d{8}T\d{6}Z)(?=\r?$)/gm;

/**
 * The iCalendar text of the calendar.
 *
 * ts-ics writes an absolute alarm trigger as `TRIGGER:<date-time>`.
 * RFC 5545 requires `VALUE=DATE-TIME` there, because the default value
 * type of TRIGGER is a duration. Without it, a parser reads the date as
 * a broken duration, and the next save writes `TRIGGER:undefined`.
 */
export const serializeIcsCalendar = (calendar: IcsCalendar): string =>
  generateIcsCalendar(calendar).replace(BARE_ABSOLUTE_TRIGGER, "TRIGGER;VALUE=DATE-TIME:$1");
