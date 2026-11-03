import {
  getCalendarDeleteMode,
  isCalendarOwner,
  belongsInMyCalendars,
  isMailboxCalendarAdmin,
} from "../calendar-ownership";
import type { Mailbox, MailboxRole } from "@/features/mailbox/types";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";

const calendar = (overrides: Partial<CalDavCalendar>): CalDavCalendar => ({
  url: "http://srv/caldav/calendars/users/me@example.com/cal/",
  displayName: "Cal",
  includeInAvailability: true,
  ...overrides,
});

describe("isCalendarOwner", () => {
  it("is true for an owner instance", () => {
    expect(
      isCalendarOwner(calendar({ resourcetype: ["collection", "calendar", "sharedOwner"] })),
    ).toBe(true);
  });

  it("is true when the resource type is unknown", () => {
    expect(isCalendarOwner(calendar({}))).toBe(true);
  });

  it("is false for a sharee instance", () => {
    expect(isCalendarOwner(calendar({ resourcetype: ["collection", "calendar", "shared"] }))).toBe(
      false,
    );
  });

  it("is false for a mailbox calendar instance", () => {
    expect(
      isCalendarOwner(
        calendar({ resourcetype: ["collection", "calendar", "shared"], ownerType: "MAILBOX" }),
      ),
    ).toBe(false);
  });
});

describe("getCalendarDeleteMode", () => {
  const sharee = {
    href: "mailto:bob@example.com",
    privilege: "read" as const,
    status: "accepted" as const,
  };

  it("returns delete for an owner without sharees", () => {
    expect(getCalendarDeleteMode(calendar({ resourcetype: ["calendar", "sharedOwner"] }))).toBe(
      "delete",
    );
  });

  it("returns delete-shared for an owner with sharees", () => {
    expect(
      getCalendarDeleteMode(
        calendar({ resourcetype: ["calendar", "sharedOwner"], sharees: [sharee] }),
      ),
    ).toBe("delete-shared");
  });

  it("returns leave for a sharee, even when other sharees exist", () => {
    expect(
      getCalendarDeleteMode(calendar({ resourcetype: ["calendar", "shared"], sharees: [sharee] })),
    ).toBe("leave");
  });
});

describe("belongsInMyCalendars", () => {
  it("returns true for an owned calendar that the user shares", () => {
    expect(
      belongsInMyCalendars(calendar({ resourcetype: ["collection", "calendar", "sharedOwner"] })),
    ).toBe(true);
  });

  it("returns false for a calendar shared with the user", () => {
    expect(
      belongsInMyCalendars(calendar({ resourcetype: ["collection", "calendar", "shared"] })),
    ).toBe(false);
  });

  it("returns true for a mailbox calendar", () => {
    expect(
      belongsInMyCalendars(
        calendar({ resourcetype: ["collection", "calendar", "shared"], ownerType: "MAILBOX" }),
      ),
    ).toBe(true);
  });
});

describe("isMailboxCalendarAdmin", () => {
  const mailboxCalendar = calendar({ ownerType: "MAILBOX", mailboxEmail: "team@example.com" });
  const mailbox = (email: string, role: MailboxRole): Mailbox => ({
    email,
    id: email,
    name: email,
    role,
    users: [],
  });

  it("is true for an admin of the mailbox", () => {
    expect(isMailboxCalendarAdmin(mailboxCalendar, [mailbox("team@example.com", "admin")])).toBe(
      true,
    );
  });

  it("is false for a sender of the mailbox", () => {
    expect(isMailboxCalendarAdmin(mailboxCalendar, [mailbox("team@example.com", "sender")])).toBe(
      false,
    );
  });

  it("is false for an admin of another mailbox", () => {
    expect(isMailboxCalendarAdmin(mailboxCalendar, [mailbox("other@example.com", "admin")])).toBe(
      false,
    );
  });

  it("is false for a calendar that a user owns", () => {
    expect(
      isMailboxCalendarAdmin(calendar({ mailboxEmail: "team@example.com" }), [
        mailbox("team@example.com", "admin"),
      ]),
    ).toBe(false);
  });
});
