import { convertIcsCalendar, type IcsAlarm, type IcsCalendar } from "ts-ics";
import { describe, expect, it } from "vitest";

import { serializeIcsCalendar } from "../serialize-ics";

const makeCalendar = (alarms: IcsAlarm[]): IcsCalendar => ({
  version: "2.0",
  prodId: "-//test//EN",
  events: [
    {
      uid: "evt-1",
      summary: "Standup",
      stamp: { date: new Date("2026-06-22T08:00:00Z") },
      start: { date: new Date("2026-06-22T14:00:00Z") },
      end: { date: new Date("2026-06-22T15:00:00Z") },
      alarms,
    },
  ],
});

describe("serializeIcsCalendar", () => {
  it("marks an absolute alarm trigger as a date-time", () => {
    const text = serializeIcsCalendar(
      makeCalendar([
        {
          action: "DISPLAY",
          description: "Reminder",
          trigger: { type: "absolute", value: { date: new Date("2026-06-22T08:00:00Z") } },
        },
      ]),
    );

    expect(text).toMatch(/^TRIGGER;VALUE=DATE-TIME:20260622T080000Z\r?$/m);
  });

  it("keeps an absolute trigger absolute after a parse", () => {
    const calendar = makeCalendar([
      {
        action: "DISPLAY",
        description: "Reminder",
        trigger: { type: "absolute", value: { date: new Date("2026-06-22T08:00:00Z") } },
      },
    ]);

    const parsed = convertIcsCalendar(undefined, serializeIcsCalendar(calendar));
    const trigger = parsed.events?.[0].alarms?.[0].trigger;

    expect(trigger?.type).toBe("absolute");
    expect(serializeIcsCalendar(parsed)).toMatch(/^TRIGGER;VALUE=DATE-TIME:20260622T080000Z\r?$/m);
  });

  it("leaves a relative trigger as it is", () => {
    const text = serializeIcsCalendar(
      makeCalendar([
        {
          action: "DISPLAY",
          description: "Reminder",
          trigger: { type: "relative", value: { before: true, minutes: 15 } },
        },
      ]),
    );

    expect(text).toMatch(/^TRIGGER:-PT15M\r?$/m);
  });
});
