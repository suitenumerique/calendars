import type { IcsAlarm, IcsDuration } from "ts-ics";

export const REMINDER_PRESETS = [
  { minutes: 5, key: "5min" },
  { minutes: 15, key: "15min" },
  { minutes: 30, key: "30min" },
  { minutes: 60, key: "1hour" },
  { minutes: 1440, key: "1day" },
  { minutes: 10080, key: "1week" },
] as const;

const DEFAULT_PRESET_MINUTES = 15;

const presetDuration = (minutes: number): IcsDuration => {
  if (minutes % 10080 === 0) return { before: true, weeks: minutes / 10080 };
  if (minutes % 1440 === 0) return { before: true, days: minutes / 1440 };
  if (minutes % 60 === 0) return { before: true, hours: minutes / 60 };
  return { before: true, minutes };
};

/**
 * The preset that the alarm matches, in minutes before the start of the
 * event. Returns null for any other trigger: an absolute date, a trigger
 * after the start, a trigger relative to the end, or a duration that is
 * not a preset.
 */
export const getPresetMinutes = (alarm: IcsAlarm): number | null => {
  const { trigger } = alarm;
  if (trigger.type !== "relative") return null;
  if (trigger.options?.related === "END") return null;

  const d = trigger.value;
  if (!d.before || d.seconds) return null;

  const minutes =
    (d.weeks || 0) * 10080 + (d.days || 0) * 1440 + (d.hours || 0) * 60 + (d.minutes || 0);
  return REMINDER_PRESETS.some((preset) => preset.minutes === minutes) ? minutes : null;
};

/**
 * A new DISPLAY alarm at the default preset. RFC 5545 requires a
 * DESCRIPTION on a DISPLAY alarm, and strict clients reject the event
 * without it.
 */
export const createDefaultAlarm = (): IcsAlarm => ({
  action: "DISPLAY",
  description: "Reminder",
  trigger: { type: "relative", value: presetDuration(DEFAULT_PRESET_MINUTES) },
});

/**
 * The alarm with its trigger moved to a preset. The other properties of
 * the alarm stay, so an alarm from another client keeps its action.
 */
export const withPresetTrigger = (alarm: IcsAlarm, minutes: number): IcsAlarm => ({
  ...alarm,
  trigger: { type: "relative", value: presetDuration(minutes) },
});
