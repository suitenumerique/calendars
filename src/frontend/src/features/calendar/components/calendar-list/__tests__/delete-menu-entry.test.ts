import { isMailboxCalendarAdmin } from "@/features/calendar/utils/calendar-ownership";
import type { Mailbox } from "@/features/mailbox/types";

import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";
import { getDeleteMenuEntry } from "../utils";

const calendar = {
  url: "http://localhost/caldav/calendars/users/u@example.com/team/",
  ownerType: "MAILBOX",
  mailboxEmail: "contact@example.com",
  syncManaged: true,
} as CalDavCalendar;

const mailbox = (role: Mailbox["role"]) => [{ email: "contact@example.com", role }] as Mailbox[];

// Same wiring as CalendarList: only an admin gets onDeleteForMailbox.
const entryFor = (role: Mailbox["role"]) =>
  getDeleteMenuEntry({
    onDelete: vi.fn(),
    syncManaged: calendar.syncManaged,
    onDeleteForMailbox: isMailboxCalendarAdmin(calendar, mailbox(role)) ? vi.fn() : undefined,
  });

describe("getDeleteMenuEntry", () => {
  it("gives a mailbox admin the delete for every mailbox user", () => {
    const entry = entryFor("admin");
    expect(entry.labelKey).toBe("calendar.list.deleteForMailbox");
    expect(entry.isDisabled).toBeFalsy();
  });

  it.each(["viewer", "editor", "sender"] as const)(
    "keeps the delete disabled for a mailbox %s",
    (role) => {
      const entry = entryFor(role);
      expect(entry.labelKey).toBe("calendar.list.delete");
      expect(entry.isDisabled).toBe(true);
      expect(entry.subTextKey).toBe("calendar.list.cannotDeleteMailboxCalendar");
    },
  );

  it("offers to leave a calendar that is not sync-managed", () => {
    const onLeave = vi.fn();
    const entry = getDeleteMenuEntry({ onDelete: vi.fn(), onLeave });
    expect(entry.labelKey).toBe("calendar.list.leaveCalendar");
    expect(entry.callback).toBe(onLeave);
    expect(entry.isDisabled).toBeFalsy();
  });
});
