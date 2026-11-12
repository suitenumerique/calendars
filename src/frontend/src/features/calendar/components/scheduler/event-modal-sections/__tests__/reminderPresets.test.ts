import { createDefaultAlarm, getPresetMinutes, withPresetTrigger } from "../reminderPresets";

import type { IcsAlarm, IcsDuration } from "ts-ics";

const relativeAlarm = (value: IcsDuration, related?: "START" | "END"): IcsAlarm => ({
  action: "DISPLAY",
  trigger: { type: "relative", value, options: related ? { related } : undefined },
});

describe("getPresetMinutes", () => {
  it("matches a preset in any unit", () => {
    expect(getPresetMinutes(relativeAlarm({ before: true, minutes: 15 }))).toBe(15);
    expect(getPresetMinutes(relativeAlarm({ before: true, minutes: 60 }))).toBe(60);
    expect(getPresetMinutes(relativeAlarm({ before: true, hours: 24 }))).toBe(1440);
    expect(getPresetMinutes(relativeAlarm({ before: true, weeks: 1 }))).toBe(10080);
  });

  it("returns null for a duration that is not a preset", () => {
    expect(getPresetMinutes(relativeAlarm({ before: true, minutes: 10 }))).toBeNull();
    expect(getPresetMinutes(relativeAlarm({ before: true, minutes: 15, seconds: 30 }))).toBeNull();
  });

  it("returns null for a trigger after the start", () => {
    expect(getPresetMinutes(relativeAlarm({ minutes: 15 }))).toBeNull();
    expect(getPresetMinutes(relativeAlarm({ before: false, minutes: 15 }))).toBeNull();
  });

  it("returns null for a trigger relative to the end", () => {
    expect(getPresetMinutes(relativeAlarm({ before: true, minutes: 15 }, "END"))).toBeNull();
  });

  it("returns null for an absolute trigger", () => {
    const alarm: IcsAlarm = {
      action: "DISPLAY",
      trigger: { type: "absolute", value: { date: new Date("2026-06-22T14:00:00Z") } },
    };
    expect(getPresetMinutes(alarm)).toBeNull();
  });
});

describe("createDefaultAlarm", () => {
  it("creates a DISPLAY alarm with a description, 15 minutes before", () => {
    const alarm = createDefaultAlarm();
    expect(alarm.action).toBe("DISPLAY");
    expect(alarm.description).toBeTruthy();
    expect(getPresetMinutes(alarm)).toBe(15);
  });
});

describe("withPresetTrigger", () => {
  it("picks the largest whole unit", () => {
    const alarm = createDefaultAlarm();
    expect(withPresetTrigger(alarm, 30).trigger.value).toEqual({ before: true, minutes: 30 });
    expect(withPresetTrigger(alarm, 60).trigger.value).toEqual({ before: true, hours: 1 });
    expect(withPresetTrigger(alarm, 1440).trigger.value).toEqual({ before: true, days: 1 });
    expect(withPresetTrigger(alarm, 10080).trigger.value).toEqual({ before: true, weeks: 1 });
  });

  it("keeps the other properties of the alarm", () => {
    const alarm: IcsAlarm = {
      action: "EMAIL",
      description: "Body",
      summary: "Subject",
      trigger: { type: "absolute", value: { date: new Date("2026-06-22T14:00:00Z") } },
    };
    expect(withPresetTrigger(alarm, 15)).toEqual({
      action: "EMAIL",
      description: "Body",
      summary: "Subject",
      trigger: { type: "relative", value: { before: true, minutes: 15 } },
    });
  });
});
