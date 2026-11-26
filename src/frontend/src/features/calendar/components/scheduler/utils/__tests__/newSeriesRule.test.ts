import { describe, expect, it } from "vitest";
import type { IcsDateObject, IcsEvent, IcsRecurrenceRule } from "ts-ics";

import { getNewSeriesRule } from "../newSeriesRule";

const utc = (iso: string): Date => new Date(`${iso}Z`);

// A wall-clock time in Paris, in summer time (UTC+2), as ts-ics parses a
// DTSTART with a TZID.
const paris = (wallClock: string): IcsDateObject => ({
  date: new Date(utc(wallClock).getTime() - 2 * 3600_000),
  type: "DATE-TIME",
  local: { date: utc(wallClock), timezone: "Europe/Paris", tzoffset: "+0200" },
});

// The instants of the occurrences at 10:00 in Paris, on these days of
// September.
const septemberAt10 = (...days: number[]): Date[] =>
  days.map((day) => paris(`2026-09-${String(day).padStart(2, "0")}T10:00:00`).date);

const weekly = (count?: number): IcsRecurrenceRule => ({ frequency: "WEEKLY", count });

const makeEvent = (
  recurrenceRule: IcsRecurrenceRule,
  extra: Pick<Partial<IcsEvent>, "start" | "exceptionDates"> = {},
): IcsEvent => ({
  uid: "uid",
  stamp: { date: utc("2026-09-01T00:00:00") },
  summary: "Event",
  start: paris("2026-09-03T10:00:00"),
  end: paris("2026-09-03T11:00:00"),
  recurrenceRule,
  ...extra,
});

describe("getNewSeriesRule", () => {
  it("gives the new series the occurrences from the cutoff", () => {
    const event = makeEvent(weekly(8));
    const occurrences = septemberAt10(3, 10, 17, 24);
    expect(getNewSeriesRule(event, utc("2026-10-01T10:00:00"), occurrences)).toEqual(weekly(4));
  });

  it("compares the occurrences as wall-clock times", () => {
    const event = makeEvent(weekly(8));
    // Summer time in Paris ends on 25 October.
    const occurrences = [utc("2026-10-22T08:00:00"), utc("2026-10-29T09:00:00")];
    expect(getNewSeriesRule(event, utc("2026-10-29T10:00:00"), occurrences)).toEqual(weekly(7));
  });

  it("keeps the count when the cutoff is the first occurrence", () => {
    const event = makeEvent(weekly(8));
    const occurrences = septemberAt10(3, 10);
    expect(getNewSeriesRule(event, utc("2026-09-03T10:00:00"), occurrences)).toEqual(weekly(8));
  });

  it("counts the occurrences that an EXDATE removes", () => {
    const event = makeEvent(weekly(8), { exceptionDates: [paris("2026-09-10T10:00:00")] });
    const occurrences = septemberAt10(3, 17, 24);
    expect(getNewSeriesRule(event, utc("2026-10-01T10:00:00"), occurrences)).toEqual(weekly(4));
  });

  it("counts each occurrence once", () => {
    const tenth = paris("2026-09-10T10:00:00");
    const event = makeEvent(weekly(8), { exceptionDates: [tenth, tenth] });
    const occurrences = septemberAt10(3, 10, 17, 24);
    expect(getNewSeriesRule(event, utc("2026-10-01T10:00:00"), occurrences)).toEqual(weekly(4));
  });

  it("compares all-day occurrences as dates", () => {
    const event = makeEvent(
      { frequency: "MONTHLY", count: 12 },
      { start: { date: utc("2026-01-31T00:00:00"), type: "DATE" } },
    );
    // A monthly rule on the 31st skips the shorter months.
    const occurrences = [utc("2026-01-31T00:00:00"), utc("2026-03-31T00:00:00")];
    expect(getNewSeriesRule(event, utc("2026-05-31T00:00:00"), occurrences)?.count).toBe(10);
  });

  it("keeps a rule with UNTIL", () => {
    const rule: IcsRecurrenceRule = {
      frequency: "WEEKLY",
      until: { date: utc("2026-12-31T00:00:00"), type: "DATE-TIME" },
    };
    expect(getNewSeriesRule(makeEvent(rule), utc("2026-10-29T10:00:00"), [])).toBe(rule);
  });

  it("keeps a rule with no end", () => {
    const rule = weekly();
    expect(getNewSeriesRule(makeEvent(rule), utc("2026-10-29T10:00:00"), [])).toBe(rule);
  });
});
