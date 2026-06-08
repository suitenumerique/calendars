import type { IcsRecurrenceRule } from "ts-ics";

import { getEndType, isForeverCount, isForeverUntil } from "../RecurrenceEditor";

function rule(overrides: Partial<IcsRecurrenceRule>): IcsRecurrenceRule {
  return {
    frequency: "DAILY",
    ...overrides,
  } as IcsRecurrenceRule;
}

function dateIn(years: number): { type: "DATE-TIME"; date: Date } {
  const d = new Date();
  d.setFullYear(d.getFullYear() + years);
  return { type: "DATE-TIME", date: d };
}

describe("RecurrenceEditor end-type classification", () => {
  describe("isForeverCount", () => {
    it("returns false for rules without COUNT", () => {
      expect(isForeverCount(rule({ frequency: "DAILY" }))).toBe(false);
    });

    it("treats DAILY COUNT=7300 (~20 years) as forever", () => {
      expect(isForeverCount(rule({ frequency: "DAILY", count: 7300 }))).toBe(true);
    });

    it("treats DAILY COUNT=50 as finite (well under 15 years)", () => {
      expect(isForeverCount(rule({ frequency: "DAILY", count: 50 }))).toBe(false);
    });

    it("treats HOURLY COUNT=720 (~30 days) as finite", () => {
      // Pins that the server's HOURLY cap doesn't get re-mapped to
      // "never" in the editor: 30 days is a real bound, not forever.
      expect(isForeverCount(rule({ frequency: "HOURLY", count: 720 }))).toBe(false);
    });

    it("treats YEARLY COUNT=100 as forever", () => {
      expect(isForeverCount(rule({ frequency: "YEARLY", count: 100 }))).toBe(true);
    });

    it("respects INTERVAL when computing coverage", () => {
      // FREQ=WEEKLY;COUNT=1000;INTERVAL=2 = 2000 weeks ≈ 38 yr → forever.
      expect(isForeverCount(rule({ frequency: "WEEKLY", count: 1000, interval: 2 }))).toBe(true);
      // FREQ=WEEKLY;COUNT=100;INTERVAL=2 = 200 weeks ≈ 3.8 yr → finite.
      expect(isForeverCount(rule({ frequency: "WEEKLY", count: 100, interval: 2 }))).toBe(false);
    });

    it("returns false for unknown FREQ (defensive)", () => {
      expect(
        isForeverCount(
          rule({
            frequency: "WHATEVER" as IcsRecurrenceRule["frequency"],
            count: 999,
          }),
        ),
      ).toBe(false);
    });
  });

  describe("isForeverUntil", () => {
    it("returns false for rules without UNTIL", () => {
      expect(isForeverUntil(rule({ frequency: "DAILY" }))).toBe(false);
    });

    it("treats UNTIL 30 years from now as forever", () => {
      expect(isForeverUntil(rule({ frequency: "DAILY", until: dateIn(30) }))).toBe(true);
    });

    it("treats UNTIL 5 years from now as finite", () => {
      expect(isForeverUntil(rule({ frequency: "DAILY", until: dateIn(5) }))).toBe(false);
    });

    it("treats past UNTIL as finite (not forever)", () => {
      expect(isForeverUntil(rule({ frequency: "DAILY", until: dateIn(-5) }))).toBe(false);
    });
  });

  describe("getEndType", () => {
    it("returns 'never' for empty or unbounded rules", () => {
      expect(getEndType(undefined)).toBe("never");
      expect(getEndType(rule({ frequency: "DAILY" }))).toBe("never");
    });

    it("returns 'count' for explicit short COUNT", () => {
      expect(getEndType(rule({ frequency: "DAILY", count: 10 }))).toBe("count");
    });

    it("returns 'never' for forever-equivalent COUNT", () => {
      expect(getEndType(rule({ frequency: "DAILY", count: 7300 }))).toBe("never");
    });

    it("returns 'date' for near UNTIL", () => {
      expect(getEndType(rule({ frequency: "DAILY", until: dateIn(2) }))).toBe("date");
    });

    it("returns 'never' for far-future UNTIL", () => {
      expect(getEndType(rule({ frequency: "DAILY", until: dateIn(25) }))).toBe("never");
    });
  });
});
