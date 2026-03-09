import type { DayOfWeek, AvailabilitySlots } from "./types";
import { generateSlotId } from "./types";

/** Map day names to iCal BYDAY abbreviations */
const DAY_TO_ICAL: Record<DayOfWeek, string> = {
  monday: "MO",
  tuesday: "TU",
  wednesday: "WE",
  thursday: "TH",
  friday: "FR",
  saturday: "SA",
  sunday: "SU",
};

/** Reverse map: iCal abbreviation to day name */
const ICAL_TO_DAY: Record<string, DayOfWeek> = Object.fromEntries(
  Object.entries(DAY_TO_ICAL).map(([k, v]) => [v, k as DayOfWeek]),
) as Record<string, DayOfWeek>;

/**
 * Anchor dates for each weekday (week of 2026-01-05, a Monday).
 * Used as DTSTART reference for recurring AVAILABLE components.
 */
const DAY_ANCHORS: Record<DayOfWeek, string> = {
  monday: "20260105",
  tuesday: "20260106",
  wednesday: "20260107",
  thursday: "20260108",
  friday: "20260109",
  saturday: "20260110",
  sunday: "20260111",
};

/**
 * Convert AvailabilitySlots to a VCALENDAR string with VAVAILABILITY.
 *
 * Groups recurring slots with identical time ranges into single
 * AVAILABLE components with multi-day BYDAY rules.
 * Specific-date slots each get their own AVAILABLE block without RRULE.
 */
export function slotsToVCalendar(slots: AvailabilitySlots): string {
  // Separate recurring vs specific
  const recurringSlots = slots.filter(
    (s) => s.when.type === "recurring",
  );
  const specificSlots = slots.filter(
    (s) => s.when.type === "specific",
  );

  // Group recurring by time range
  const groups = new Map<
    string,
    { days: DayOfWeek[]; start: string; end: string }
  >();
  for (const slot of recurringSlots) {
    if (slot.when.type !== "recurring") continue;
    const key = `${slot.start}-${slot.end}`;
    const group = groups.get(key);
    if (group) {
      group.days.push(slot.when.day);
    } else {
      groups.set(key, {
        days: [slot.when.day],
        start: slot.start,
        end: slot.end,
      });
    }
  }

  const blocks: string[] = [];

  // Recurring blocks
  for (const { days, start, end } of groups.values()) {
    const byDay = days.map((d) => DAY_TO_ICAL[d]).join(",");
    const anchor = DAY_ANCHORS[days[0]];
    const startTime = start.replace(":", "");
    const endTime = end.replace(":", "");
    blocks.push(`BEGIN:AVAILABLE
DTSTART:${anchor}T${startTime}00
DTEND:${anchor}T${endTime}00
RRULE:FREQ=WEEKLY;BYDAY=${byDay}
END:AVAILABLE`);
  }

  // Specific-date blocks (skip past dates)
  const today = new Date().toISOString().slice(0, 10);
  for (const slot of specificSlots) {
    if (slot.when.type !== "specific") continue;
    if (slot.when.date < today) continue;
    const dateStr = slot.when.date.replace(/-/g, "");
    const startTime = slot.start.replace(":", "");
    const endTime = slot.end.replace(":", "");
    blocks.push(`BEGIN:AVAILABLE
DTSTART:${dateStr}T${startTime}00
DTEND:${dateStr}T${endTime}00
END:AVAILABLE`);
  }

  const inner = blocks.length > 0 ? "\n" + blocks.join("\n") + "\n" : "\n";

  return `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Calendars//Working Hours//EN
BEGIN:VAVAILABILITY${inner}END:VAVAILABILITY
END:VCALENDAR`;
}

/**
 * Parse a VCALENDAR with VAVAILABILITY back into AvailabilitySlots.
 */
export function vCalendarToSlots(vcalendar: string): AvailabilitySlots {
  const slots: AvailabilitySlots = [];

  const availableRegex = /BEGIN:AVAILABLE[\s\S]*?END:AVAILABLE/g;
  let match;

  while ((match = availableRegex.exec(vcalendar)) !== null) {
    const block = match[0];

    const startMatch = block.match(
      /DTSTART:(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})\d{2}/,
    );
    const endMatch = block.match(
      /DTEND:\d{8}T(\d{2})(\d{2})\d{2}/,
    );

    if (!startMatch || !endMatch) continue;

    const start = `${startMatch[4]}:${startMatch[5]}`;
    const end = `${endMatch[1]}:${endMatch[2]}`;
    const dateStr = `${startMatch[1]}-${startMatch[2]}-${startMatch[3]}`;

    const byDayMatch = block.match(/BYDAY=([A-Z,]+)/);

    if (byDayMatch) {
      // Recurring: create one slot per day in the BYDAY list
      const days = byDayMatch[1].split(",");
      for (const icalDay of days) {
        const dayName = ICAL_TO_DAY[icalDay];
        if (dayName) {
          slots.push({
            id: generateSlotId(),
            when: { type: "recurring", day: dayName },
            start,
            end,
          });
        }
      }
    } else {
      // Specific date — skip past dates
      const today = new Date().toISOString().slice(0, 10);
      if (dateStr < today) continue;

      slots.push({
        id: generateSlotId(),
        when: { type: "specific", date: dateStr },
        start,
        end,
      });
    }
  }

  return slots;
}
