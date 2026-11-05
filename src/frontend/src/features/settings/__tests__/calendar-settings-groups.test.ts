import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { groupCalendarsForSettings } from "../calendar-settings-groups";

const calendar = (displayName: string, extra: Partial<CalDavCalendar> = {}) =>
  ({
    url: `http://localhost/caldav/calendars/users/me@example.com/${displayName}/`,
    displayName,
    resourcetype: ["collection", "calendar"],
    ...extra,
  }) as CalDavCalendar;

const names = (calendars: CalDavCalendar[]) => calendars.map((cal) => cal.displayName);

describe("groupCalendarsForSettings", () => {
  it("puts the calendars that the user owns first, sorted by name", () => {
    const groups = groupCalendarsForSettings([
      calendar("work"),
      calendar("team", { resourcetype: ["collection", "calendar", "shared"] }),
      calendar("home"),
    ]);

    expect(names(groups.mine)).toEqual(["home", "work"]);
    expect(names(groups.shared)).toEqual(["team"]);
  });

  it("puts mailbox calendars with the user's calendars, like the sidebar", () => {
    const groups = groupCalendarsForSettings([
      calendar("support", {
        resourcetype: ["collection", "calendar", "shared"],
        ownerType: "MAILBOX",
        mailboxEmail: "support@example.com",
      }),
      calendar("old", { resourcetype: ["collection", "calendar", "shared"], hidden: true }),
    ]);

    expect(names(groups.mine)).toEqual(["support"]);
    expect(names(groups.shared)).toEqual(["old"]);
  });

  it("keeps the order of calendars with the same name when one is hidden", () => {
    const first = calendar("contact", { url: "http://localhost/a/", mailboxEmail: "contact@a.fr" });
    const second = calendar("contact", {
      url: "http://localhost/b/",
      mailboxEmail: "contact@b.fr",
    });

    const visible = groupCalendarsForSettings([first, second]);
    const oneHidden = groupCalendarsForSettings([second, { ...first, hidden: true }]);

    expect(visible.mine.map((cal) => cal.url)).toEqual([first.url, second.url]);
    expect(oneHidden.mine.map((cal) => cal.url)).toEqual([first.url, second.url]);
  });

  it("sorts by name before URL", () => {
    const groups = groupCalendarsForSettings([
      calendar("zeta", { url: "http://localhost/a/" }),
      calendar("alpha", { url: "http://localhost/z/" }),
    ]);

    expect(names(groups.mine)).toEqual(["alpha", "zeta"]);
  });
});
