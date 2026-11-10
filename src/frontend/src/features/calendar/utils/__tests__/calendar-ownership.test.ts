import {
  compareCalendarGroups,
  getCalendarDeleteMode,
  getCalendarGroup,
  isCalendarOwner,
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

describe("getCalendarGroup", () => {
  const shared = ["collection", "calendar", "shared"];

  it("puts an owner instance in the own group", () => {
    expect(getCalendarGroup(calendar({ resourcetype: ["collection", "calendar"] }))).toBe("own");
  });

  it("puts the calendar of a mailbox the user belongs to in the mailbox group", () => {
    expect(
      getCalendarGroup(calendar({ resourcetype: shared, ownerType: "MAILBOX", syncManaged: true })),
    ).toBe("mailbox");
  });

  it("puts a mailbox calendar that an admin shared with the user in the shared group", () => {
    expect(getCalendarGroup(calendar({ resourcetype: shared, ownerType: "MAILBOX" }))).toBe(
      "shared",
    );
  });

  it("puts a calendar that a user shares in the shared group", () => {
    expect(getCalendarGroup(calendar({ resourcetype: shared }))).toBe("shared");
  });
});

describe("compareCalendarGroups", () => {
  it("orders own, then mailbox, then shared", () => {
    const own = calendar({ resourcetype: ["collection", "calendar"] });
    const mailbox = calendar({
      resourcetype: ["collection", "calendar", "shared"],
      ownerType: "MAILBOX",
      syncManaged: true,
    });
    const shared = calendar({ resourcetype: ["collection", "calendar", "shared"] });

    expect([shared, mailbox, own].sort(compareCalendarGroups)).toEqual([own, mailbox, shared]);
    expect(compareCalendarGroups(own, own)).toBe(0);
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
