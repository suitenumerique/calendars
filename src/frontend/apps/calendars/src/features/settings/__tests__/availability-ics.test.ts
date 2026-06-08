import {
  slotsToVCalendar,
  vCalendarToSlots,
  InvalidAvailabilityValueError,
} from "../availability-ics";

import type { AvailabilitySlots } from "../types";

describe("availability-ics", () => {
  // Freeze "today" so tests with specific dates never become stale.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  describe("slotsToVCalendar", () => {
    it("converts recurring weekday slots to VCALENDAR", () => {
      const slots: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "recurring", day: "monday" },
          start: "09:00",
          end: "17:00",
        },
        {
          id: "2",
          when: { type: "recurring", day: "friday" },
          start: "09:00",
          end: "17:00",
        },
      ];
      const result = slotsToVCalendar(slots);
      expect(result).toContain("BEGIN:VCALENDAR");
      expect(result).toContain("BEGIN:VAVAILABILITY");
      expect(result).toContain("RRULE:FREQ=WEEKLY;BYDAY=MO,FR");
      expect(result).toContain("T090000");
      expect(result).toContain("T170000");
    });

    it("creates separate blocks for different time ranges", () => {
      const slots: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "recurring", day: "monday" },
          start: "09:00",
          end: "12:00",
        },
        {
          id: "2",
          when: { type: "recurring", day: "monday" },
          start: "14:00",
          end: "18:00",
        },
      ];
      const result = slotsToVCalendar(slots);
      const count = (result.match(/BEGIN:AVAILABLE/g) || []).length;
      expect(count).toBe(2);
    });

    it("handles specific-date slots without RRULE", () => {
      const slots: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "specific", date: "2026-03-15" },
          start: "10:00",
          end: "14:00",
        },
      ];
      const result = slotsToVCalendar(slots);
      expect(result).toContain("DTSTART:20260315T100000");
      expect(result).toContain("DTEND:20260315T140000");
      expect(result).not.toContain("RRULE");
    });

    it("handles mixed recurring and specific-date slots", () => {
      const slots: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "recurring", day: "tuesday" },
          start: "09:00",
          end: "17:00",
        },
        {
          id: "2",
          when: { type: "specific", date: "2026-04-01" },
          start: "10:00",
          end: "15:00",
        },
      ];
      const result = slotsToVCalendar(slots);
      expect(result).toContain("RRULE:FREQ=WEEKLY;BYDAY=TU");
      expect(result).toContain("DTSTART:20260401T100000");
      expect(result).not.toMatch(/RRULE.*\n.*20260401/);
    });

    it("handles empty slots array", () => {
      const result = slotsToVCalendar([]);
      expect(result).toContain("BEGIN:VAVAILABILITY");
      expect(result).not.toContain("BEGIN:AVAILABLE");
    });
  });

  describe("vCalendarToSlots", () => {
    it("parses recurring AVAILABLE blocks into slots", () => {
      const vcal = `BEGIN:VCALENDAR
BEGIN:VAVAILABILITY
BEGIN:AVAILABLE
DTSTART:20260105T090000
DTEND:20260105T170000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR
END:AVAILABLE
END:VAVAILABILITY
END:VCALENDAR`;
      const result = vCalendarToSlots(vcal);
      expect(result).toHaveLength(3);
      expect(result.map((s) => (s.when as { day: string }).day)).toEqual([
        "monday",
        "wednesday",
        "friday",
      ]);
      expect(result[0].start).toBe("09:00");
      expect(result[0].end).toBe("17:00");
    });

    it("parses specific-date AVAILABLE blocks", () => {
      const vcal = `BEGIN:VCALENDAR
BEGIN:VAVAILABILITY
BEGIN:AVAILABLE
DTSTART:20260315T100000
DTEND:20260315T140000
END:AVAILABLE
END:VAVAILABILITY
END:VCALENDAR`;
      const result = vCalendarToSlots(vcal);
      expect(result).toHaveLength(1);
      expect(result[0].when).toEqual({ type: "specific", date: "2026-03-15" });
      expect(result[0].start).toBe("10:00");
      expect(result[0].end).toBe("14:00");
    });

    it("round-trips recurring slots", () => {
      const original: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "recurring", day: "monday" },
          start: "08:00",
          end: "12:00",
        },
        {
          id: "2",
          when: { type: "recurring", day: "monday" },
          start: "14:00",
          end: "18:00",
        },
        {
          id: "3",
          when: { type: "recurring", day: "wednesday" },
          start: "09:00",
          end: "17:00",
        },
      ];
      const vcal = slotsToVCalendar(original);
      const parsed = vCalendarToSlots(vcal);

      expect(parsed).toHaveLength(3);
      // Check monday slots
      const monSlots = parsed.filter((s) => s.when.type === "recurring" && s.when.day === "monday");
      expect(monSlots).toHaveLength(2);
      expect(monSlots.map((s) => s.start).sort()).toEqual(["08:00", "14:00"]);
    });

    it("round-trips specific-date slots", () => {
      const original: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "specific", date: "2026-12-25" },
          start: "10:00",
          end: "14:00",
        },
      ];
      const vcal = slotsToVCalendar(original);
      const parsed = vCalendarToSlots(vcal);
      expect(parsed).toHaveLength(1);
      expect(parsed[0].when).toEqual({ type: "specific", date: "2026-12-25" });
      expect(parsed[0].start).toBe("10:00");
      expect(parsed[0].end).toBe("14:00");
    });

    it("returns empty array for invalid input", () => {
      expect(vCalendarToSlots("not valid ics")).toEqual([]);
    });

    it("returns empty array for VCALENDAR with no AVAILABLE", () => {
      const vcal = `BEGIN:VCALENDAR\nBEGIN:VAVAILABILITY\nEND:VAVAILABILITY\nEND:VCALENDAR`;
      expect(vCalendarToSlots(vcal)).toEqual([]);
    });

    it("filters out past specific dates on parse", () => {
      const vcal = `BEGIN:VCALENDAR
BEGIN:VAVAILABILITY
BEGIN:AVAILABLE
DTSTART:20200101T090000
DTEND:20200101T170000
END:AVAILABLE
END:VAVAILABILITY
END:VCALENDAR`;
      expect(vCalendarToSlots(vcal)).toEqual([]);
    });

    it("filters out past specific dates on save", () => {
      const slots: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "specific", date: "2020-01-01" },
          start: "09:00",
          end: "17:00",
        },
        {
          id: "2",
          when: { type: "recurring", day: "monday" },
          start: "09:00",
          end: "17:00",
        },
      ];
      const result = slotsToVCalendar(slots);
      expect(result).not.toContain("20200101");
      expect(result).toContain("BYDAY=MO");
    });
  });

  describe("input validation (regression)", () => {
    // The serializer hand-builds VAVAILABILITY because ts-ics doesn't
    // support RFC 7953. To compensate for the lack of a real generator,
    // it validates every time/date string at the boundary so a malformed
    // value can never line-inject into the ICS body. These tests pin
    // that contract — if someone removes the validators, the smuggled
    // bytes come back and these tests must fail.

    it.each([
      "9:00", // missing leading zero on hour
      "09:0", // missing leading zero on minute
      "24:00", // hour out of range
      "12:60", // minute out of range
      "09:00\nMETHOD:CANCEL", // line-injection attempt
      "09:00\rinjected",
      "09-00", // wrong separator
      "morning",
      "",
    ])("rejects malformed recurring start time %s", (badStart) => {
      const slots: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "recurring", day: "monday" },
          start: badStart,
          end: "17:00",
        },
      ];
      expect(() => slotsToVCalendar(slots)).toThrow(InvalidAvailabilityValueError);
    });

    it.each(["09:00\nDTSTART:19700101T000000", "09:00;HACK"])(
      "rejects malformed specific-slot end time %s",
      (badEnd) => {
        const slots: AvailabilitySlots = [
          {
            id: "1",
            when: { type: "specific", date: "2026-12-25" },
            start: "09:00",
            end: badEnd,
          },
        ];
        expect(() => slotsToVCalendar(slots)).toThrow(InvalidAvailabilityValueError);
      },
    );

    it.each([
      "2026/01/01", // wrong separator
      "2026-01-01\nMETHOD:CANCEL",
      "2026-01-01\rinjected",
      "tomorrow",
      "20260101", // missing separators
    ])("rejects malformed specific-slot date %s", (badDate) => {
      const slots: AvailabilitySlots = [
        {
          id: "1",
          when: { type: "specific", date: badDate },
          start: "09:00",
          end: "17:00",
        },
      ];
      expect(() => slotsToVCalendar(slots)).toThrow(InvalidAvailabilityValueError);
    });

    it("error message identifies which field failed", () => {
      try {
        slotsToVCalendar([
          {
            id: "1",
            when: { type: "recurring", day: "monday" },
            start: "09:00",
            end: "bad",
          },
        ]);
        throw new Error("expected throw");
      } catch (e) {
        expect(e).toBeInstanceOf(InvalidAvailabilityValueError);
        expect((e as Error).message).toContain("end");
      }
    });
  });
});
