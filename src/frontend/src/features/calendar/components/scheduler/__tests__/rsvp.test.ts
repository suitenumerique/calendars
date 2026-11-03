import { toOccurrenceInstant } from "../utils/rsvp";

const SECOND = new Date("2026-11-03T09:00:00Z");

describe("toOccurrenceInstant", () => {
  it("converts a wall-clock time in its timezone to an instant", () => {
    const local = { date: SECOND, timezone: "Europe/Paris", tzoffset: "+0100" };
    const value = { date: SECOND, type: "DATE-TIME" as const, local };

    expect(toOccurrenceInstant(value)).toEqual(new Date("2026-11-03T08:00:00Z"));
  });

  it("tells apart the two times of the repeated hour", () => {
    // On 2026-10-25, Paris shows 02:30 twice: at 00:30Z and at 01:30Z.
    const wallClock = new Date("2026-10-25T02:30:00Z");
    const at = (tzoffset: string) => ({
      date: wallClock,
      type: "DATE-TIME" as const,
      local: { date: wallClock, timezone: "Europe/Paris", tzoffset },
    });

    expect(toOccurrenceInstant(at("+0200"))).toEqual(new Date("2026-10-25T00:30:00Z"));
    expect(toOccurrenceInstant(at("+0100"))).toEqual(new Date("2026-10-25T01:30:00Z"));
  });

  it("keeps an all-day date at midnight UTC", () => {
    const day = new Date("2026-11-03T00:00:00Z");

    expect(toOccurrenceInstant({ date: day, type: "DATE" })).toEqual(day);
  });
});
