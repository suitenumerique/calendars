import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import { getDefaultCalendar, sortCalendars } from "../calendar-order";

const shared = ["collection", "calendar", "shared"];

const calendar = (displayName: string, extra: Partial<CalDavCalendar> = {}) =>
  ({
    url: `http://localhost/caldav/calendars/users/me@example.com/${displayName}/`,
    displayName,
    resourcetype: ["collection", "calendar"],
    ...extra,
  }) as CalDavCalendar;

const names = (calendars: CalDavCalendar[]) => calendars.map((cal) => cal.displayName);

describe("sortCalendars", () => {
  it("puts the placed calendars first, in their order", () => {
    const sorted = sortCalendars([
      calendar("alpha"),
      calendar("team", { resourcetype: shared, order: 0 }),
      calendar("work", { order: 1 }),
    ]);

    expect(names(sorted)).toEqual(["team", "work", "alpha"]);
  });

  it("sorts the calendars without a place by group, then by name", () => {
    const sorted = sortCalendars([
      calendar("work"),
      calendar("team", { resourcetype: shared }),
      calendar("contact", { resourcetype: shared, ownerType: "MAILBOX", syncManaged: true }),
      calendar("home"),
    ]);

    expect(names(sorted)).toEqual(["home", "work", "contact", "team"]);
  });

  it("keeps the order of calendars with the same name when one is hidden", () => {
    const first = calendar("contact", { url: "http://localhost/a/" });
    const second = calendar("contact", { url: "http://localhost/b/" });

    const visible = sortCalendars([first, second]);
    const oneHidden = sortCalendars([second, { ...first, hidden: true }]);

    expect(visible.map((cal) => cal.url)).toEqual([first.url, second.url]);
    expect(oneHidden.map((cal) => cal.url)).toEqual([first.url, second.url]);
  });

  it("does not change the given list", () => {
    const calendars = [calendar("zeta"), calendar("alpha")];

    sortCalendars(calendars);

    expect(names(calendars)).toEqual(["zeta", "alpha"]);
  });
});

describe("getDefaultCalendar", () => {
  const urls = (...calendars: CalDavCalendar[]) => new Set(calendars.map((cal) => cal.url));

  it("takes the first visible calendar that the user can write to", () => {
    const own = calendar("own");
    const contact = calendar("contact", { ownerType: "MAILBOX" });

    expect(getDefaultCalendar([own, contact], urls(contact))).toBe(contact);
  });

  it("follows the display order when several calendars are visible", () => {
    const own = calendar("own");
    const contact = calendar("contact");

    expect(getDefaultCalendar([own, contact], urls(contact, own))).toBe(own);
  });

  it("skips a visible read-only calendar", () => {
    const own = calendar("own");
    const shared = calendar("shared", { readOnly: true });
    const team = calendar("team");

    expect(getDefaultCalendar([own, shared, team], urls(shared, team))).toBe(team);
  });

  it("takes the first writable calendar when no visible one is writable", () => {
    const shared = calendar("shared", { readOnly: true });
    const own = calendar("own");

    expect(getDefaultCalendar([shared, own], urls(shared))).toBe(own);
    expect(getDefaultCalendar([shared, own], new Set())).toBe(own);
  });

  it("falls back to the first calendar when all are read-only", () => {
    const first = calendar("a", { readOnly: true });

    expect(getDefaultCalendar([first, calendar("b", { readOnly: true })], new Set())).toBe(first);
  });

  it("is undefined without calendars", () => {
    expect(getDefaultCalendar([], new Set())).toBeUndefined();
  });
});
