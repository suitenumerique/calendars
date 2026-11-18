import type { IcsAttendee, IcsEvent, IcsOrganizer } from "ts-ics";

import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";

const same = (a?: string, b?: string): boolean => !!a && !!b && a.toLowerCase() === b.toLowerCase();

/**
 * Give the addresses that the user can schedule with: the email of the
 * user and the mailboxes of the given calendars that the user can write
 * to. Give the hidden calendars too, as the server counts them.
 */
export const userAddresses = (
  email: string | undefined,
  calendars: Pick<CalDavCalendar, "mailboxEmail" | "readOnly">[],
): string[] => [
  ...(email ? [email] : []),
  ...calendars.flatMap((c) => (c.mailboxEmail && !c.readOnly ? [c.mailboxEmail] : [])),
];

/**
 * Tell if the user organizes the event in a calendar. An event without
 * organizer is an organizer copy.
 *
 * When the event contains the identity of the calendar, the identity
 * decides. Otherwise, the user organizes the event when the organizer
 * is one of the addresses of the user. Only the given component counts;
 * the server examines all the stored components.
 */
export const isOrganizerCopy = (
  event: Partial<IcsEvent> | null | undefined,
  identity: string | undefined,
  addresses: string[],
): boolean => {
  const organizer = event?.organizer?.email;
  if (!organizer) return true;
  if (same(organizer, identity)) return true;
  if (event.attendees?.some((a) => same(a.email, identity))) return false;
  return addresses.some((a) => same(a, organizer));
};

/**
 * Give the attendees after an organizer change. The new organizer is no
 * longer an attendee. The previous organizer becomes an attendee that
 * accepts.
 */
export const changeAttendees = (
  attendees: IcsAttendee[],
  organizer: IcsOrganizer,
  previous: IcsOrganizer,
): IcsAttendee[] => [
  ...attendees.filter((a) => !same(a.email, organizer.email) && !same(a.email, previous.email)),
  { email: previous.email, name: previous.name, partstat: "ACCEPTED" },
];

/**
 * Merge an edit of the changed attendees into the form attendees. The
 * previous organizer is not kept, because the change adds it again. The
 * attendee entry of the new organizer stays in the form if it exists, so
 * that it comes back when the user selects the source calendar again.
 */
export const mergeAttendeeEdits = (
  edited: IcsAttendee[],
  current: IcsAttendee[],
  organizer: IcsOrganizer,
  previous: IcsOrganizer,
): IcsAttendee[] => [
  ...edited.filter((a) => !same(a.email, previous.email)),
  ...current.filter((a) => same(a.email, organizer.email)),
];

/**
 * Make the address the organizer of the event. When the previous
 * organizer is given and is another address, it becomes an attendee that
 * accepts. The server does the same change when a meeting moves to a
 * calendar with another identity. This function does not change the
 * SEQUENCE.
 */
export const changeOrganizer = (
  event: IcsEvent,
  organizer: IcsOrganizer,
  previous: IcsOrganizer | undefined,
): IcsEvent => {
  if (!previous || same(previous.email, organizer.email)) {
    return { ...event, organizer };
  }
  return {
    ...event,
    organizer,
    attendees: changeAttendees(event.attendees ?? [], organizer, previous),
  };
};
