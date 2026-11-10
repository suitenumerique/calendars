import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { sortCalendarsForSettings } from "../calendar-settings-sort";

const calendar = (displayName: string, extra: Partial<CalDavCalendar> = {}) =>
  ({
    url: `http://localhost/caldav/calendars/users/me@example.com/${displayName}/`,
    displayName,
    resourcetype: ["collection", "calendar"],
    ...extra,
  }) as CalDavCalendar;

const names = (calendars: CalDavCalendar[]) => calendars.map((cal) => cal.displayName);

describe("sortCalendarsForSettings", () => {
  it("sorts the calendars of the user and of others by name", () => {
    const sorted = sortCalendarsForSettings([
      calendar("work"),
      calendar("team", { resourcetype: ["collection", "calendar", "shared"] }),
      calendar("home"),
    ]);

    expect(names(sorted)).toEqual(["home", "team", "work"]);
  });

  it("keeps the order of calendars with the same name when one is hidden", () => {
    const first = calendar("contact", { url: "http://localhost/a/", mailboxEmail: "contact@a.fr" });
    const second = calendar("contact", {
      url: "http://localhost/b/",
      mailboxEmail: "contact@b.fr",
    });

    const visible = sortCalendarsForSettings([first, second]);
    const oneHidden = sortCalendarsForSettings([second, { ...first, hidden: true }]);

    expect(visible.map((cal) => cal.url)).toEqual([first.url, second.url]);
    expect(oneHidden.map((cal) => cal.url)).toEqual([first.url, second.url]);
  });

  it("sorts by name before URL", () => {
    const sorted = sortCalendarsForSettings([
      calendar("zeta", { url: "http://localhost/a/" }),
      calendar("alpha", { url: "http://localhost/z/" }),
    ]);

    expect(names(sorted)).toEqual(["alpha", "zeta"]);
  });

  it("does not change the given list", () => {
    const calendars = [calendar("zeta"), calendar("alpha")];

    sortCalendarsForSettings(calendars);

    expect(names(calendars)).toEqual(["zeta", "alpha"]);
  });
});
