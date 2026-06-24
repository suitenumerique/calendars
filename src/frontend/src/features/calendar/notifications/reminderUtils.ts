/**
 * Pure helpers for turning an event's VALARM components into concrete,
 * fireable reminders. Kept free of React / browser APIs so they can be
 * unit-tested in isolation.
 */
import type { IcsAlarm, IcsEvent } from "ts-ics";

const MS = {
  second: 1_000,
  minute: 60_000,
  hour: 3_600_000,
  day: 86_400_000,
  week: 604_800_000,
} as const;

/**
 * VALARM actions we surface as in-app / browser notifications. EMAIL
 * alarms are intentionally excluded — those are meant to be delivered by
 * a mail server, not the browser. Anything without an ACTION defaults to
 * DISPLAY per RFC 5545.
 */
const CLIENT_ACTIONS = new Set(["DISPLAY", "AUDIO"]);

/**
 * Absolute instant (ms since epoch) of an event's start, or null.
 *
 * All-day events (`type === "DATE"`) are stored by ts-ics as UTC midnight;
 * we reinterpret that calendar date as *local* midnight so an all-day
 * reminder fires relative to the user's day rather than being shifted by
 * their UTC offset.
 */
export const getEventInstantMs = (event: IcsEvent): number | null => {
  const date = event.start?.date;
  if (!(date instanceof Date)) return null;
  if (event.start?.type === "DATE") {
    return new Date(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()).getTime();
  }
  return date.getTime();
};

/**
 * Resolve the absolute instant at which an alarm should fire.
 *
 * - Relative triggers are interpreted against the event start; `before`
 *   (a "-PT15M"-style duration) fires earlier, otherwise later.
 * - Absolute triggers carry their own datetime.
 *
 * Returns null when the trigger cannot be resolved.
 */
export const getAlarmTriggerMs = (alarm: IcsAlarm, eventInstantMs: number): number | null => {
  const trigger = alarm.trigger;
  if (!trigger) return null;

  if (trigger.type === "absolute") {
    const date = trigger.value?.date;
    return date instanceof Date ? date.getTime() : null;
  }

  const d = trigger.value;
  if (!d) return null;
  const magnitude =
    (d.weeks || 0) * MS.week +
    (d.days || 0) * MS.day +
    (d.hours || 0) * MS.hour +
    (d.minutes || 0) * MS.minute +
    (d.seconds || 0) * MS.second;
  // `before === false`/undefined means the duration is "after start".
  return d.before === false ? eventInstantMs + magnitude : eventInstantMs - magnitude;
};

/** A reminder that is ready to be shown to the user. */
export interface DueReminder {
  key: string;
  event: IcsEvent;
  calendarUrl: string;
  alarm: IcsAlarm;
  triggerMs: number;
  eventInstantMs: number;
}

/**
 * Stable identity for a fired reminder, so the same alarm never fires
 * twice. Recurring instances are disambiguated by RECURRENCE-ID (falling
 * back to the occurrence start), and multiple alarms on one event by
 * their resolved trigger instant.
 */
export const reminderKey = (
  calendarUrl: string,
  event: IcsEvent,
  triggerMs: number,
  eventInstantMs: number,
): string => {
  const recId = event.recurrenceId?.value?.date;
  const occurrence = recId instanceof Date ? recId.getTime() : eventInstantMs;
  return `${calendarUrl}|${event.uid ?? ""}|${occurrence}|${triggerMs}`;
};

/**
 * Given the loaded upcoming events, return the reminders that are due:
 * the trigger time has passed but is no older than `backfillMs`.
 *
 * Bounding on the *trigger* time (not the event start) is what keeps a
 * fresh page load from dumping every long-lead reminder ("1 day"/"1 week
 * before") whose trigger elapsed days ago. The small backfill window only
 * recovers reminders that came due during a brief gap (a backgrounded tab,
 * a laptop waking from sleep, or the seconds between polls); the
 * fired-reminder store dedups across reloads.
 */
export const collectDueReminders = (
  events: { event: IcsEvent; calendarUrl: string }[],
  nowMs: number,
  backfillMs: number,
): DueReminder[] => {
  const due: DueReminder[] = [];

  for (const { event, calendarUrl } of events) {
    const alarms = event.alarms;
    if (!alarms?.length) continue;

    const eventInstantMs = getEventInstantMs(event);
    if (eventInstantMs == null) continue;

    for (const alarm of alarms) {
      const action = (alarm.action ?? "DISPLAY").toUpperCase();
      if (!CLIENT_ACTIONS.has(action)) continue;

      const triggerMs = getAlarmTriggerMs(alarm, eventInstantMs);
      if (triggerMs == null) continue;
      if (triggerMs > nowMs) continue; // not due yet
      if (triggerMs < nowMs - backfillMs) continue; // due too long ago

      due.push({
        key: reminderKey(calendarUrl, event, triggerMs, eventInstantMs),
        event,
        calendarUrl,
        alarm,
        triggerMs,
        eventInstantMs,
      });
    }
  }

  return due;
};

/**
 * Index master events' VALARM lists by UID. Built from a non-expanded
 * CalDAV fetch, where recurring masters still carry their alarms.
 */
export const buildAlarmMap = (events: IcsEvent[]): Map<string, IcsAlarm[]> => {
  const map = new Map<string, IcsAlarm[]>();
  for (const event of events) {
    if (event.uid && event.alarms?.length) {
      map.set(event.uid, event.alarms);
    }
  }
  return map;
};

/**
 * Re-attach alarms to event instances that lost them. CalDAV `expand`
 * gives correct per-occurrence start times but (in sabre/vobject) drops
 * VALARM from the generated instances, so recurring-event reminders would
 * otherwise never fire. Instances that already carry alarms are left
 * untouched.
 */
export const withMasterAlarms = (
  instances: { event: IcsEvent; calendarUrl: string }[],
  alarmsByUid: Map<string, IcsAlarm[]>,
): { event: IcsEvent; calendarUrl: string }[] =>
  instances.map(({ event, calendarUrl }) => {
    if (event.alarms?.length || !event.uid) return { event, calendarUrl };
    const alarms = alarmsByUid.get(event.uid);
    return alarms ? { event: { ...event, alarms }, calendarUrl } : { event, calendarUrl };
  });
