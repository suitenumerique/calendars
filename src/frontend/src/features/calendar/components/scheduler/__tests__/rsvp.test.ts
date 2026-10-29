import {
  buildOccurrenceReply,
  findRsvpBlocker,
  resolveRsvpEvent,
  toOccurrenceInstant,
  toSeriesWallClock,
} from "../utils/rsvp";

import type { IcsAttendeePartStatusType, IcsEvent } from "ts-ics";

const UID = "event-uid";
const USER = "bob@example.com";
const START = new Date("2026-11-02T09:00:00Z");
const END = new Date("2026-11-02T10:00:00Z");
const SECOND = new Date("2026-11-03T09:00:00Z");

const master = (overrides: Partial<IcsEvent> = {}): IcsEvent =>
  ({
    uid: UID,
    stamp: { date: START },
    start: { date: START, type: "DATE-TIME" },
    end: { date: END, type: "DATE-TIME" },
    summary: "Weekly",
    organizer: { email: "alice@example.com" },
    recurrenceRule: { frequency: "DAILY", count: 3 },
    exceptionDates: [{ date: new Date("2026-11-04T09:00:00Z"), type: "DATE-TIME" }],
    attendees: [
      { email: "Bob@Example.com", partstat: "NEEDS-ACTION" },
      { email: "carol@example.com", partstat: "ACCEPTED" },
    ],
    ...overrides,
  }) as IcsEvent;

const override = (overrides: Partial<IcsEvent> = {}) =>
  master({
    start: { date: SECOND, type: "DATE-TIME" },
    recurrenceRule: undefined,
    exceptionDates: undefined,
    recurrenceId: { value: { date: SECOND, type: "DATE-TIME" } },
    ...overrides,
  });

const scheduled = (date: Date) => ({ date, scheduled: true });
const unscheduled = (date: Date) => ({ date, scheduled: false });

const blocker = (events: IcsEvent[] | undefined, occurrence?: { date: Date; scheduled: boolean }) =>
  findRsvpBlocker(resolveRsvpEvent(events, UID, occurrence?.date), USER, occurrence?.scheduled);

const answer = (events: IcsEvent[], instant: Date, partstat: IcsAttendeePartStatusType) =>
  buildOccurrenceReply(resolveRsvpEvent(events, UID, instant), instant, USER, partstat);

describe("findRsvpBlocker", () => {
  it("allows an answer to a confirmed event", () => {
    expect(blocker([master()])).toBeNull();
  });

  it("reports a deleted event", () => {
    expect(blocker([])).toBe("deleted");
    expect(blocker(undefined)).toBe("deleted");
    expect(blocker([master({ uid: "other" })])).toBe("deleted");
  });

  it("reports a cancelled event", () => {
    expect(blocker([master({ status: "CANCELLED" })])).toBe("cancelled");
  });

  it("reports a removed attendee", () => {
    const events = [master({ attendees: [{ email: "carol@example.com" }] })];
    expect(blocker(events)).toBe("notAttendee");
  });

  it("allows an answer to a scheduled occurrence", () => {
    expect(blocker([master()], scheduled(SECOND))).toBeNull();
  });

  it("reports an occurrence that the server no longer expands", () => {
    expect(blocker([master()], unscheduled(SECOND))).toBe("cancelled");
  });

  it("reports a cancelled override", () => {
    const events = [master(), override({ status: "CANCELLED" })];
    expect(blocker(events, scheduled(SECOND))).toBe("cancelled");
    expect(blocker(events, scheduled(START))).toBeNull();
  });

  it("reports an attendee removed from one override", () => {
    const events = [master(), override({ attendees: [] })];
    expect(blocker(events, scheduled(SECOND))).toBe("notAttendee");
    expect(blocker(events, scheduled(START))).toBeNull();
  });
});

describe("buildOccurrenceReply", () => {
  it("moves the master to the occurrence and changes only the PARTSTAT", () => {
    const reply = answer([master()], SECOND, "ACCEPTED");

    expect(reply?.summary).toBe("Weekly");
    expect(reply?.start.date).toEqual(SECOND);
    expect(reply?.end?.date).toEqual(new Date("2026-11-03T10:00:00Z"));
    expect(reply?.recurrenceRule).toBeUndefined();
    expect(reply?.exceptionDates).toBeUndefined();
    expect(reply?.attendees).toEqual([
      { email: "Bob@Example.com", partstat: "ACCEPTED" },
      { email: "carol@example.com", partstat: "ACCEPTED" },
    ]);
  });

  it("gives a zoned start the wall-clock time of the occurrence", () => {
    // 09:00 in Paris is 08:00 UTC.
    const zoned = master({
      start: {
        date: new Date("2026-11-02T08:00:00Z"),
        type: "DATE-TIME",
        local: { date: START, timezone: "Europe/Paris", tzoffset: "+0100" },
      },
    });
    const instant = new Date("2026-11-03T08:00:00Z");

    const reply = answer([zoned], instant, "ACCEPTED");

    expect(reply?.start.date).toEqual(instant);
    expect(reply?.start.local).toEqual({
      date: SECOND,
      timezone: "Europe/Paris",
      tzoffset: "+0100",
    });
  });

  it("uses the server override of the occurrence", () => {
    const moved = override({
      summary: "Moved by the organizer",
      start: { date: new Date("2026-11-03T14:00:00Z"), type: "DATE-TIME" },
    });

    const reply = answer([master(), moved], SECOND, "DECLINED");

    expect(reply?.summary).toBe("Moved by the organizer");
    expect(reply?.start.date).toEqual(new Date("2026-11-03T14:00:00Z"));
    expect(reply?.attendees?.[0].partstat).toBe("DECLINED");
  });

  it("returns undefined when the server has no VEVENT for the UID", () => {
    expect(answer([], SECOND, "ACCEPTED")).toBeUndefined();
  });
});

describe("toOccurrenceInstant", () => {
  it("converts a wall-clock time in its timezone to an instant", () => {
    const local = { date: SECOND, timezone: "Europe/Paris", tzoffset: "+0100" };
    const value = { date: SECOND, type: "DATE-TIME" as const, local };

    expect(toOccurrenceInstant(SECOND, value)).toEqual(new Date("2026-11-03T08:00:00Z"));
  });

  it("applies the summer offset", () => {
    const summer = new Date("2026-07-01T09:00:00Z");
    const value = {
      date: summer,
      type: "DATE-TIME" as const,
      local: { date: summer, timezone: "Europe/Paris", tzoffset: "+0200" },
    };

    expect(toOccurrenceInstant(summer, value)).toEqual(new Date("2026-07-01T07:00:00Z"));
  });

  it("tells apart the two times of the repeated hour", () => {
    // On 2026-10-25, Paris shows 02:30 twice: at 00:30Z and at 01:30Z.
    const wallClock = new Date("2026-10-25T02:30:00Z");
    const at = (tzoffset: string) => ({
      date: wallClock,
      type: "DATE-TIME" as const,
      local: { date: wallClock, timezone: "Europe/Paris", tzoffset },
    });

    expect(toOccurrenceInstant(wallClock, at("+0200"))).toEqual(new Date("2026-10-25T00:30:00Z"));
    expect(toOccurrenceInstant(wallClock, at("+0100"))).toEqual(new Date("2026-10-25T01:30:00Z"));
  });

  it("keeps an all-day date at midnight UTC", () => {
    const day = new Date("2026-11-03T00:00:00Z");

    expect(toOccurrenceInstant(day, { date: day, type: "DATE" })).toEqual(day);
  });
});

describe("toSeriesWallClock", () => {
  it("gives the wall-clock time in the series timezone", () => {
    // A Paris series at 09:00. A UTC browser gives the instant 08:00Z.
    const paris = master({
      start: {
        date: new Date("2026-11-02T08:00:00Z"),
        type: "DATE-TIME",
        local: { date: START, timezone: "Europe/Paris", tzoffset: "+0100" },
      },
    });

    expect(toSeriesWallClock(paris, new Date("2026-11-03T08:00:00Z"))).toEqual(SECOND);
  });

  it("keeps the instant for a series without timezone", () => {
    expect(toSeriesWallClock(master(), SECOND)).toEqual(SECOND);
  });
});
