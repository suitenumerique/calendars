import {
  slotsToVCalendar,
  vCalendarToSlots,
} from "../availability-ics";
import type { AvailabilitySlots } from "../types";

describe("availability-ics", () => {
  describe("slotsToVCalendar", () => {
    it("converts recurring weekday slots to VCALENDAR", () => {
      const slots: AvailabilitySlots = [
        { id: "1", when: { type: "recurring", day: "monday" }, start: "09:00", end: "17:00" },
        { id: "2", when: { type: "recurring", day: "friday" }, start: "09:00", end: "17:00" },
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
        { id: "1", when: { type: "recurring", day: "monday" }, start: "09:00", end: "12:00" },
        { id: "2", when: { type: "recurring", day: "monday" }, start: "14:00", end: "18:00" },
      ];
      const result = slotsToVCalendar(slots);
      const count = (result.match(/BEGIN:AVAILABLE/g) || []).length;
      expect(count).toBe(2);
    });

    it("handles specific-date slots without RRULE", () => {
      const slots: AvailabilitySlots = [
        { id: "1", when: { type: "specific", date: "2026-03-15" }, start: "10:00", end: "14:00" },
      ];
      const result = slotsToVCalendar(slots);
      expect(result).toContain("DTSTART:20260315T100000");
      expect(result).toContain("DTEND:20260315T140000");
      expect(result).not.toContain("RRULE");
    });

    it("handles mixed recurring and specific-date slots", () => {
      const slots: AvailabilitySlots = [
        { id: "1", when: { type: "recurring", day: "tuesday" }, start: "09:00", end: "17:00" },
        { id: "2", when: { type: "specific", date: "2026-04-01" }, start: "10:00", end: "15:00" },
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
        "monday", "wednesday", "friday",
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
        { id: "1", when: { type: "recurring", day: "monday" }, start: "08:00", end: "12:00" },
        { id: "2", when: { type: "recurring", day: "monday" }, start: "14:00", end: "18:00" },
        { id: "3", when: { type: "recurring", day: "wednesday" }, start: "09:00", end: "17:00" },
      ];
      const vcal = slotsToVCalendar(original);
      const parsed = vCalendarToSlots(vcal);

      expect(parsed).toHaveLength(3);
      // Check monday slots
      const monSlots = parsed.filter(
        (s) => s.when.type === "recurring" && s.when.day === "monday",
      );
      expect(monSlots).toHaveLength(2);
      expect(monSlots.map((s) => s.start).sort()).toEqual(["08:00", "14:00"]);
    });

    it("round-trips specific-date slots", () => {
      const original: AvailabilitySlots = [
        { id: "1", when: { type: "specific", date: "2026-12-25" }, start: "10:00", end: "14:00" },
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
        { id: "1", when: { type: "specific", date: "2020-01-01" }, start: "09:00", end: "17:00" },
        { id: "2", when: { type: "recurring", day: "monday" }, start: "09:00", end: "17:00" },
      ];
      const result = slotsToVCalendar(slots);
      expect(result).not.toContain("20200101");
      expect(result).toContain("BYDAY=MO");
    });
  });
});
