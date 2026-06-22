import {
  buildAlarmMap,
  collectDueReminders,
  getAlarmTriggerMs,
  getEventInstantMs,
  reminderKey,
  withMasterAlarms,
} from "../reminderUtils";

import type { IcsAlarm, IcsEvent } from "ts-ics";

const MIN = 60_000;
const BACKFILL = 5 * MIN;

const EVENT_START = new Date("2026-06-22T14:00:00Z");

const relativeAlarm = (
  value: Partial<{ minutes: number; hours: number; days: number; weeks: number; before: boolean }>,
  action = "DISPLAY",
): IcsAlarm => ({
  action,
  trigger: { type: "relative", value: { before: true, ...value } },
});

const makeEvent = (overrides: Partial<IcsEvent> = {}): IcsEvent =>
  ({
    uid: "evt-1",
    summary: "Standup",
    start: { type: "DATE-TIME", date: EVENT_START },
    ...overrides,
  }) as IcsEvent;

describe("getEventInstantMs", () => {
  it("returns the start instant", () => {
    expect(getEventInstantMs(makeEvent())).toBe(EVENT_START.getTime());
  });

  it("returns null when start is missing", () => {
    expect(getEventInstantMs({ uid: "x" } as IcsEvent)).toBeNull();
  });

  it("treats an all-day (DATE) start as local midnight, not UTC midnight", () => {
    // ts-ics stores all-day starts as UTC midnight; we want local midnight
    // so the reminder isn't shifted by the viewer's UTC offset.
    const utcMidnight = new Date(Date.UTC(2026, 5, 22));
    const allDay = { uid: "ad", start: { type: "DATE", date: utcMidnight } } as IcsEvent;
    const expected = new Date(2026, 5, 22).getTime();
    expect(getEventInstantMs(allDay)).toBe(expected);
  });
});

describe("getAlarmTriggerMs", () => {
  const start = EVENT_START.getTime();

  it("fires before the start for a 15-minute relative alarm", () => {
    expect(getAlarmTriggerMs(relativeAlarm({ minutes: 15 }), start)).toBe(start - 15 * 60_000);
  });

  it("combines weeks/days/hours/minutes", () => {
    const ms = getAlarmTriggerMs(relativeAlarm({ days: 1, hours: 2 }), start);
    expect(ms).toBe(start - (86_400_000 + 2 * 3_600_000));
  });

  it("fires after the start when before is false", () => {
    const alarm: IcsAlarm = {
      action: "DISPLAY",
      trigger: { type: "relative", value: { before: false, minutes: 10 } },
    };
    expect(getAlarmTriggerMs(alarm, start)).toBe(start + 10 * 60_000);
  });

  it("handles absolute triggers", () => {
    const at = new Date("2026-06-22T13:00:00Z");
    const alarm: IcsAlarm = {
      action: "DISPLAY",
      trigger: { type: "absolute", value: { type: "DATE-TIME", date: at } },
    } as IcsAlarm;
    expect(getAlarmTriggerMs(alarm, start)).toBe(at.getTime());
  });
});

describe("reminderKey", () => {
  it("is stable for the same alarm/event", () => {
    const event = makeEvent();
    const k1 = reminderKey("/cal/", event, 1000, EVENT_START.getTime());
    const k2 = reminderKey("/cal/", event, 1000, EVENT_START.getTime());
    expect(k1).toBe(k2);
  });

  it("differs across recurring occurrences", () => {
    const base = makeEvent();
    const occurrence = makeEvent({
      recurrenceId: { value: { type: "DATE-TIME", date: new Date("2026-06-23T14:00:00Z") } },
    } as Partial<IcsEvent>);
    expect(reminderKey("/cal/", base, 1, 1)).not.toBe(reminderKey("/cal/", occurrence, 1, 1));
  });
});

describe("collectDueReminders", () => {
  const start = EVENT_START.getTime();
  const triggerAt = (mins: number) => start - mins * MIN; // trigger for an N-min-before alarm

  it("returns a reminder just after its trigger passes", () => {
    const event = makeEvent({ alarms: [relativeAlarm({ minutes: 15 })] });
    const now = triggerAt(15) + 30_000; // 30s past the trigger
    const due = collectDueReminders([{ event, calendarUrl: "/c/" }], now, BACKFILL);
    expect(due).toHaveLength(1);
    expect(due[0].triggerMs).toBe(triggerAt(15));
  });

  it("does not return a reminder before its trigger", () => {
    const event = makeEvent({ alarms: [relativeAlarm({ minutes: 15 })] });
    const now = start - 30 * MIN; // trigger (15 min before) is still in the future
    expect(collectDueReminders([{ event, calendarUrl: "/c/" }], now, BACKFILL)).toHaveLength(0);
  });

  it("does not back-fire a trigger that elapsed before the backfill window", () => {
    const event = makeEvent({ alarms: [relativeAlarm({ days: 1 })] });
    // "1 day before" trigger elapsed ~12h ago — far outside the 5-min backfill.
    const now = triggerAt(0) - 12 * 60 * MIN + 1; // 12h before start
    expect(collectDueReminders([{ event, calendarUrl: "/c/" }], now, BACKFILL)).toHaveLength(0);
  });

  it("fires at the moment of start for a 0-minute alarm within backfill", () => {
    const event = makeEvent({ alarms: [relativeAlarm({ minutes: 0 })] });
    const now = start + 30_000; // 30s after start
    expect(collectDueReminders([{ event, calendarUrl: "/c/" }], now, BACKFILL)).toHaveLength(1);
  });

  it("ignores EMAIL alarms (delivered server-side)", () => {
    const event = makeEvent({ alarms: [relativeAlarm({ minutes: 15 }, "EMAIL")] });
    const now = triggerAt(15) + 30_000;
    expect(collectDueReminders([{ event, calendarUrl: "/c/" }], now, BACKFILL)).toHaveLength(0);
  });

  it("returns one entry per due alarm on the same event", () => {
    const event = makeEvent({
      alarms: [relativeAlarm({ minutes: 5 }), relativeAlarm({ minutes: 3 })],
    });
    const now = triggerAt(3) + 30_000; // both 5-min and 3-min triggers within backfill
    expect(collectDueReminders([{ event, calendarUrl: "/c/" }], now, BACKFILL)).toHaveLength(2);
  });

  it("ignores events without alarms", () => {
    const event = makeEvent();
    expect(collectDueReminders([{ event, calendarUrl: "/c/" }], start, BACKFILL)).toHaveLength(0);
  });
});

describe("buildAlarmMap / withMasterAlarms", () => {
  const alarms = [relativeAlarm({ minutes: 15 })];

  it("indexes alarms by uid, skipping events without alarms", () => {
    const master = makeEvent({ uid: "series-1", alarms });
    const noAlarm = makeEvent({ uid: "series-2" });
    const map = buildAlarmMap([master, noAlarm]);
    expect(map.get("series-1")).toBe(alarms);
    expect(map.has("series-2")).toBe(false);
  });

  it("re-attaches master alarms to expanded instances that lost them", () => {
    const instance = makeEvent({ uid: "series-1", alarms: undefined });
    const map = buildAlarmMap([makeEvent({ uid: "series-1", alarms })]);
    const merged = withMasterAlarms([{ event: instance, calendarUrl: "/c/" }], map);
    expect(merged[0].event.alarms).toBe(alarms);
  });

  it("leaves instances that already have alarms untouched", () => {
    const ownAlarms = [relativeAlarm({ minutes: 30 })];
    const instance = makeEvent({ uid: "series-1", alarms: ownAlarms });
    const map = buildAlarmMap([makeEvent({ uid: "series-1", alarms })]);
    const merged = withMasterAlarms([{ event: instance, calendarUrl: "/c/" }], map);
    expect(merged[0].event.alarms).toBe(ownAlarms);
  });

  it("leaves instances with no matching master unchanged", () => {
    const instance = makeEvent({ uid: "orphan", alarms: undefined });
    const merged = withMasterAlarms([{ event: instance, calendarUrl: "/c/" }], new Map());
    expect(merged[0].event.alarms).toBeUndefined();
  });
});
