import {
  buildOccurrenceReply,
  findRsvpBlocker,
  resolveRsvpEvent,
  toSeriesWallClock,
} from "../helpers/rsvp";

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

const replyTo = (events: IcsEvent[], instant: Date, partstat: IcsAttendeePartStatusType) =>
  buildOccurrenceReply(resolveRsvpEvent(events, UID, instant), instant, USER, partstat);

describe("findRsvpBlocker", () => {
  it("allows a response to a confirmed event", () => {
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

  it("allows a response to a scheduled occurrence", () => {
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

  describe("for all occurrences of a copy without master", () => {
    const THIRD = new Date("2026-11-04T09:00:00Z");
    const third = (overrides: Partial<IcsEvent> = {}) =>
      override({
        start: { date: THIRD, type: "DATE-TIME" },
        recurrenceId: { value: { date: THIRD, type: "DATE-TIME" } },
        ...overrides,
      });

    it("allows a response when one override lists the attendee", () => {
      expect(blocker([override(), third()])).toBeNull();
      expect(blocker([override({ attendees: [] }), third()])).toBeNull();
      expect(blocker([override({ status: "CANCELLED" }), third()])).toBeNull();
    });

    it("reports a removed attendee when no live override lists the attendee", () => {
      const events = [override({ attendees: [] }), third({ status: "CANCELLED" })];
      expect(blocker(events)).toBe("notAttendee");
    });

    it("reports a cancelled event when all overrides are cancelled", () => {
      const events = [override({ status: "CANCELLED" }), third({ status: "CANCELLED" })];
      expect(blocker(events)).toBe("cancelled");
    });
  });
});

describe("buildOccurrenceReply", () => {
  it("moves the master to the occurrence and changes only the PARTSTAT", () => {
    const reply = replyTo([master()], SECOND, "ACCEPTED");

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

    const reply = replyTo([zoned], instant, "ACCEPTED");

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

    const reply = replyTo([master(), moved], SECOND, "DECLINED");

    expect(reply?.summary).toBe("Moved by the organizer");
    expect(reply?.start.date).toEqual(new Date("2026-11-03T14:00:00Z"));
    expect(reply?.attendees?.[0].partstat).toBe("DECLINED");
  });

  it("returns undefined when the server has no VEVENT for the UID", () => {
    expect(replyTo([], SECOND, "ACCEPTED")).toBeUndefined();
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
