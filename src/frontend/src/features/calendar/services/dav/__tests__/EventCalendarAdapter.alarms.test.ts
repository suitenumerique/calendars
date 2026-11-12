import { describe, expect, it } from "vitest";

import { EventCalendarAdapter } from "../EventCalendarAdapter";

import type { IcsAlarm, IcsEvent } from "ts-ics";

const ALARMS: IcsAlarm[] = [
  {
    action: "DISPLAY",
    description: "Reminder",
    trigger: { type: "relative", value: { before: true, minutes: 10 } },
  },
  {
    action: "EMAIL",
    summary: "Subject",
    description: "Body",
    trigger: { type: "relative", value: { before: true, days: 1 } },
  },
];

const makeEvent = (alarms?: IcsAlarm[]): IcsEvent => ({
  uid: "evt-1",
  summary: "Standup",
  stamp: { date: new Date("2026-06-22T08:00:00Z") },
  start: { date: new Date("2026-06-22T14:00:00Z") },
  end: { date: new Date("2026-06-22T15:00:00Z") },
  alarms,
});

describe("alarms round trip", () => {
  it("keeps the alarms from the ICS event to the grid event and back", () => {
    const adapter = new EventCalendarAdapter();
    const ecEvent = adapter.icsEventToEventCalendarEvent(makeEvent(ALARMS), "/calendars/a/");

    expect(adapter.toIcsEvent(ecEvent).alarms).toEqual(ALARMS);
  });

  it("writes no alarms for an event that has none", () => {
    const adapter = new EventCalendarAdapter();
    const ecEvent = adapter.icsEventToEventCalendarEvent(makeEvent(), "/calendars/a/");

    expect(adapter.toIcsEvent(ecEvent).alarms).toBeUndefined();
  });
});
