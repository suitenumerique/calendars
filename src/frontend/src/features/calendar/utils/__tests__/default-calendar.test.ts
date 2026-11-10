import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import { getDefaultCalendar } from "../default-calendar";

const calendar = (url: string, extra: Partial<CalDavCalendar> = {}) =>
  ({ url, displayName: url, ...extra }) as CalDavCalendar;

describe("getDefaultCalendar", () => {
  it("skips a read-only calendar placed first", () => {
    const shared = calendar("shared", { readOnly: true });
    const own = calendar("own");

    expect(getDefaultCalendar([shared, own])).toBe(own);
  });

  it("takes the first calendar when the user can write to it", () => {
    const own = calendar("own");

    expect(getDefaultCalendar([own, calendar("other")])).toBe(own);
  });

  it("falls back to the first calendar when all are read-only", () => {
    const first = calendar("a", { readOnly: true });

    expect(getDefaultCalendar([first, calendar("b", { readOnly: true })])).toBe(first);
  });

  it("is undefined without calendars", () => {
    expect(getDefaultCalendar([])).toBeUndefined();
  });
});
