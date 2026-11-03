import type { Mailbox } from "@/features/mailbox/types";
import type { CalDavCalendar } from "../services/dav/types/caldav-service";

/**
 * The wording of the confirmation before a DELETE on the calendar.
 * It does not tell if the server accepts the DELETE.
 *
 * - `delete`: an owner instance with no sharees in the fetched data.
 * - `delete-shared`: an owner instance with sharees. They lose it too.
 * - `leave`: a sharee instance. Only the user's own access goes away.
 */
export type CalendarDeleteMode = "delete" | "delete-shared" | "leave";

/**
 * Tell if the current user owns the calendar.
 *
 * SabreDAV adds `CS:shared` to the resource type of a sharee instance.
 * The owner instance has `CS:shared-owner` instead, which the DAV
 * parser turns into `sharedOwner`. The URL does not help: SabreDAV
 * puts each sharee instance in the sharee's own calendar home.
 * Without resource type data, the user counts as the owner.
 */
export const isCalendarOwner = (calendar: CalDavCalendar): boolean =>
  !(calendar.resourcetype ?? []).includes("shared");

/**
 * Tell if the calendar goes in the "My calendars" section.
 *
 * This is about display, not ownership. A mailbox calendar is a sharee
 * instance, but the user acts for the mailbox, so it goes there too.
 */
export const belongsInMyCalendars = (calendar: CalDavCalendar): boolean =>
  calendar.ownerType === "MAILBOX" || isCalendarOwner(calendar);

export const getCalendarDeleteMode = (calendar: CalDavCalendar): CalendarDeleteMode => {
  if (!isCalendarOwner(calendar)) {
    return "leave";
  }
  return calendar.sharees?.length ? "delete-shared" : "delete";
};

/**
 * Returns whether the given mailboxes show the user as an admin of the
 * mailbox that owns the calendar.
 */
export const isMailboxCalendarAdmin = (calendar: CalDavCalendar, mailboxes: Mailbox[]): boolean =>
  calendar.ownerType === "MAILBOX" &&
  mailboxes.some((mailbox) => mailbox.email === calendar.mailboxEmail && mailbox.role === "admin");
