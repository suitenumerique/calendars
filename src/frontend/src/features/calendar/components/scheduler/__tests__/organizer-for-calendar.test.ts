/**
 * Tests for organizer determination in mailbox calendars.
 *
 * When a user creates an event in a mailbox calendar, the ORGANIZER
 * must be the mailbox email — otherwise SabreDAV won't set the
 * X-LS-Is-Mailbox header and Django will send the invite via SMTP
 * from the system address instead of via Messages from the mailbox.
 */

import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";

/**
 * Pure-function equivalent of the organizer logic in EventModal.
 * Takes `selectedCalendarUrl` (the dropdown value) so the result
 * stays in sync when the user switches calendars.
 */
function getOrganizerForCalendar(
  selectedCalendarUrl: string,
  calendars: Pick<CalDavCalendar, "url" | "mailboxEmail">[],
  eventOrganizer: { email: string } | undefined,
  userEmail: string,
): { email: string } | undefined {
  if (eventOrganizer) return eventOrganizer;

  const mailboxEmail = selectedCalendarUrl
    ? calendars.find((c) => c.url === selectedCalendarUrl)?.mailboxEmail
    : undefined;

  return mailboxEmail ? { email: mailboxEmail } : { email: userEmail };
}

// -- Test fixtures ----------------------------------------------------------

const USER_EMAIL = "alice@example.com";

const PERSONAL_CAL: Pick<CalDavCalendar, "url" | "mailboxEmail"> = {
  url: "/calendars/users/alice@example.com/default/",
  mailboxEmail: undefined,
};

const MAILBOX_CAL: Pick<CalDavCalendar, "url" | "mailboxEmail"> = {
  url: "/calendars/users/alice@example.com/shared-mbx-uuid/",
  mailboxEmail: "team@company.com",
};

const ALL_CALENDARS = [PERSONAL_CAL, MAILBOX_CAL];

// ---------------------------------------------------------------------------

describe("Organizer for mailbox calendars", () => {
  it("uses mailbox email when selected calendar is a mailbox", () => {
    const organizer = getOrganizerForCalendar(
      MAILBOX_CAL.url,
      ALL_CALENDARS,
      undefined,
      USER_EMAIL,
    );
    expect(organizer?.email).toBe("team@company.com");
  });

  it("uses user email when selected calendar is personal", () => {
    const organizer = getOrganizerForCalendar(
      PERSONAL_CAL.url,
      ALL_CALENDARS,
      undefined,
      USER_EMAIL,
    );
    expect(organizer?.email).toBe(USER_EMAIL);
  });

  it("uses mailbox email when user switches from personal to mailbox calendar", () => {
    // The key scenario: user started on personal calendar, then
    // switched to the mailbox calendar via the dropdown.
    const organizer = getOrganizerForCalendar(
      MAILBOX_CAL.url, // the dropdown selection
      ALL_CALENDARS,
      undefined,
      USER_EMAIL,
    );
    expect(organizer?.email).toBe("team@company.com");
  });

  it("preserves existing organizer for edited events", () => {
    const existingOrganizer = { email: "original@example.com" };
    const organizer = getOrganizerForCalendar(
      MAILBOX_CAL.url,
      ALL_CALENDARS,
      existingOrganizer,
      USER_EMAIL,
    );
    expect(organizer?.email).toBe("original@example.com");
  });

  it("uses user email when switching from mailbox to personal", () => {
    const organizer = getOrganizerForCalendar(
      PERSONAL_CAL.url, // switched back to personal
      ALL_CALENDARS,
      undefined,
      USER_EMAIL,
    );
    expect(organizer?.email).toBe(USER_EMAIL);
  });
});
