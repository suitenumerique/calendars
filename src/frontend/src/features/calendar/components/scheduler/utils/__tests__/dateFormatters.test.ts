import { describe, expect, it } from "vitest";

import { formatDateTimeLocal, parseDateTimeLocal } from "../dateFormatters";

describe("parseDateTimeLocal", () => {
  it("parses the datetime-local shape as local time components", () => {
    const date = parseDateTimeLocal("2026-01-29T15:07");
    expect(date.getFullYear()).toBe(2026);
    expect(date.getMonth()).toBe(0);
    expect(date.getDate()).toBe(29);
    expect(date.getHours()).toBe(15);
    expect(date.getMinutes()).toBe(7);
    expect(date.getSeconds()).toBe(0);
    expect(date.getMilliseconds()).toBe(0);
  });

  it("round-trips with formatDateTimeLocal", () => {
    for (const value of ["2026-01-29T15:07", "2026-07-14T00:00", "2024-02-29T23:59"]) {
      expect(formatDateTimeLocal(parseDateTimeLocal(value))).toBe(value);
    }
  });

  it("parses optional seconds and fractional seconds", () => {
    const withSeconds = parseDateTimeLocal("2026-01-29T15:07:42");
    expect(withSeconds.getSeconds()).toBe(42);

    const withMillis = parseDateTimeLocal("2026-01-29T15:07:42.5");
    expect(withMillis.getMilliseconds()).toBe(500);
  });

  it("falls back to Date parsing for non datetime-local shapes", () => {
    const utc = parseDateTimeLocal("2026-01-29T15:07:00Z");
    expect(utc.getTime()).toBe(Date.UTC(2026, 0, 29, 15, 7, 0));
  });
});
