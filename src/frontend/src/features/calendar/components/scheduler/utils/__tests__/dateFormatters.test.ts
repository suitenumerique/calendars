import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  formatDateLocal,
  formatDateTimeLocal,
  isValidDateInput,
  parseDateLocal,
  parseDateTimeLocal,
  shiftEnd,
} from "../dateFormatters";

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

describe("years below 1000", () => {
  it("round-trips a datetime-local value", () => {
    for (const value of ["0002-11-26T10:00", "0020-11-26T10:00", "0202-11-26T10:00"]) {
      expect(formatDateTimeLocal(parseDateTimeLocal(value))).toBe(value);
    }
  });

  it("round-trips a date value", () => {
    expect(formatDateLocal(parseDateLocal("0020-11-26"))).toBe("0020-11-26");
  });
});

describe("daylight saving time", () => {
  const initialTz = process.env.TZ;

  beforeEach(() => {
    // 2000-03-26 has a DST gap at 02:00 in Paris; 2026-03-26 has none.
    process.env.TZ = "Europe/Paris";
  });

  afterEach(() => {
    process.env.TZ = initialTz;
  });

  it("keeps a time that is valid on the parsed date", () => {
    expect(formatDateTimeLocal(parseDateTimeLocal("2026-03-26T02:30"))).toBe("2026-03-26T02:30");
  });
});

/**
 * Apply a sequence of start values as the event form does: the end moves
 * from the last valid start.
 */
const typeStarts = (start: string, end: string, nextStarts: string[], isAllDay: boolean) => {
  let lastValidStart = start;
  let lastEnd = end;
  for (const next of nextStarts) {
    lastEnd = shiftEnd(lastValidStart, lastEnd, next, isAllDay);
    if (isValidDateInput(next, isAllDay)) {
      lastValidStart = next;
    }
  }
  return lastEnd;
};

describe("shiftEnd", () => {
  it("keeps the duration when the start moves", () => {
    expect(shiftEnd("2026-11-26T10:00", "2026-11-26T11:30", "2026-11-27T14:00", false)).toBe(
      "2026-11-27T15:30",
    );
  });

  it("keeps the duration of an all-day event", () => {
    expect(shiftEnd("2026-11-26", "2026-11-28", "2026-12-01", true)).toBe("2026-12-03");
  });

  it("keeps the end through the steps of a typed year", () => {
    expect(
      typeStarts(
        "2026-11-26T10:00",
        "2026-11-26T11:00",
        ["0002-11-26T10:00", "0020-11-26T10:00", "0202-11-26T10:00", "2027-11-26T10:00"],
        false,
      ),
    ).toBe("2027-11-26T11:00");
  });

  it("keeps the end when the start is empty or partial", () => {
    expect(shiftEnd("2026-11-26T10:00", "2026-11-26T11:00", "", false)).toBe("2026-11-26T11:00");
  });

  it("keeps the duration when a cleared start is completed", () => {
    expect(
      typeStarts("2026-11-26T10:00", "2026-11-26T11:00", ["", "2026-11-27T10:00"], false),
    ).toBe("2026-11-27T11:00");
  });

  describe("daylight saving time", () => {
    const initialTz = process.env.TZ;

    beforeEach(() => {
      // DST starts on 2026-03-29 and on 2027-03-28 in Paris.
      process.env.TZ = "Europe/Paris";
    });

    afterEach(() => {
      process.env.TZ = initialTz;
    });

    it("keeps the days of an all-day event through the steps of a typed year", () => {
      expect(
        typeStarts(
          "2026-03-28",
          "2026-03-30",
          ["0002-03-28", "0020-03-28", "0202-03-28", "2027-03-28"],
          true,
        ),
      ).toBe("2027-03-30");
    });
  });
});
