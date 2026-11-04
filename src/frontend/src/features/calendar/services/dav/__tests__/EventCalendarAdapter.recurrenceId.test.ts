import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { EventCalendarAdapter } from "../EventCalendarAdapter";

describe("toIcsEvent recurrence ID", () => {
  const initialTz = process.env.TZ;

  beforeEach(() => {
    // West of UTC, midnight UTC is on the day before in local time.
    process.env.TZ = "America/New_York";
  });

  afterEach(() => {
    process.env.TZ = initialTz;
  });

  it("keeps the date of an all-day occurrence", () => {
    const occurrence = new Date(Date.UTC(2026, 10, 10));
    const ics = new EventCalendarAdapter().toIcsEvent(
      {
        id: "1",
        start: new Date(2026, 10, 10),
        end: new Date(2026, 10, 11),
        allDay: true,
        extendedProps: { recurrenceId: occurrence },
      },
      { defaultTimezone: "Europe/Paris" },
    );

    expect(ics.recurrenceId?.value.type).toBe("DATE");
    expect(ics.recurrenceId?.value.date.toISOString()).toBe("2026-11-10T00:00:00.000Z");
  });
});
