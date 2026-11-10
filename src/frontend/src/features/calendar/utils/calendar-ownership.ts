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
 * The category of a calendar: the user owns it, a mailbox the user
 * belongs to owns it, or another user shares it. It selects the icon of
 * the calendar and breaks ties in the sort.
 */
export type CalendarGroup = "own" | "mailbox" | "shared";

const GROUP_RANK: Record<CalendarGroup, number> = { own: 0, mailbox: 1, shared: 2 };

/**
 * A mailbox calendar is a sharee instance. The user acts for the mailbox
 * only through the membership that Messages syncs. A mailbox admin can
 * also share the calendar with an outside user, who sees it as shared.
 */
export const getCalendarGroup = (calendar: CalDavCalendar): CalendarGroup => {
  if (isCalendarOwner(calendar)) return "own";
  if (calendar.ownerType === "MAILBOX" && calendar.syncManaged) return "mailbox";
  return "shared";
};

/** Order two calendars by group. Returns 0 inside a group. */
export const compareCalendarGroups = (a: CalDavCalendar, b: CalDavCalendar): number =>
  GROUP_RANK[getCalendarGroup(a)] - GROUP_RANK[getCalendarGroup(b)];

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
