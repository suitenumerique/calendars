import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { isValidDateInput, shiftEnd } from "../shiftEnd";

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
