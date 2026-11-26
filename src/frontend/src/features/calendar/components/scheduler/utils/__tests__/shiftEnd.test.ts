import { describe, expect, it } from "vitest";

import { shiftEnd } from "../shiftEnd";

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
    let start = "2026-11-26T10:00";
    let end = "2026-11-26T11:00";
    for (const next of [
      "0002-11-26T10:00",
      "0020-11-26T10:00",
      "0202-11-26T10:00",
      "2027-11-26T10:00",
    ]) {
      end = shiftEnd(start, end, next, false);
      start = next;
    }
    expect(end).toBe("2027-11-26T11:00");
  });

  it("keeps the end when the start is empty or partial", () => {
    expect(shiftEnd("2026-11-26T10:00", "2026-11-26T11:00", "", false)).toBe("2026-11-26T11:00");
    expect(shiftEnd("", "2026-11-26T11:00", "2026-11-27T10:00", false)).toBe("2026-11-26T11:00");
  });
});
