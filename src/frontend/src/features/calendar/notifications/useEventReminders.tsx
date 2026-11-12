import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { IcsEvent } from "ts-ics";

import { useCalendarContext } from "../contexts/CalendarContext";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import {
  buildAlarmMap,
  collectDueReminders,
  withMasterAlarms,
  type DueReminder,
} from "./reminderUtils";
import { showBrowserNotification } from "./browserNotifications";
import { loadFiredReminders, saveFiredReminders } from "./firedReminderStore";

// Refetch the upcoming-events window on this cadence; cheap in-memory
// trigger evaluation runs more often so reminders fire near their minute.
const FETCH_INTERVAL_MS = 5 * 60_000;
const TICK_INTERVAL_MS = 30_000;
// Window must reach far enough ahead to load events whose earliest alarm
// (up to "1 week before") could become due before the next refetch.
const LOOKAHEAD_MS = 8 * 86_400_000;
// Only fire reminders whose trigger came due within this window, so a
// fresh load doesn't replay long-elapsed reminders. Wide enough to recover
// reminders missed during a backgrounded tab / sleep / between polls.
const BACKFILL_MS = 5 * 60_000;

/**
 * Drives in-app + browser notifications for event reminders (VALARM) while
 * the app is open. It independently polls a near-term window across all
 * visible calendars — the calendar grid only loads the range currently in
 * view, which would otherwise miss reminders for today while browsing
 * another month.
 */
export const useEventReminders = () => {
  const { t, i18n } = useTranslation();
  const { caldavService, visibleCalendarUrls, isConnected } = useCalendarContext();

  const upcomingRef = useRef<{ event: IcsEvent; calendarUrl: string }[]>([]);
  const firedRef = useRef<Map<string, number>>(new Map());
  // Keep formatting helpers current without re-creating the timers.
  const tRef = useRef(t);
  tRef.current = t;
  const localeRef = useRef(i18n.language);
  localeRef.current = i18n.language;

  // Restore the already-fired keys so a reload doesn't replay reminders.
  useEffect(() => {
    firedRef.current = loadFiredReminders(Date.now());
  }, []);

  // Notification permission is requested from a user gesture (saving an
  // event with a reminder), not here — browsers ignore/deny prompts that
  // aren't tied to an interaction. Without permission we degrade to
  // in-app toasts.

  const fire = useCallback((reminder: DueReminder) => {
    const tr = tRef.current;
    const title = reminder.event.summary?.trim() || tr("calendar.event.reminders.untitled");
    const time = new Intl.DateTimeFormat(localeRef.current, {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(reminder.eventInstantMs));
    const body = tr("calendar.event.reminders.notificationBody", { time });

    showBrowserNotification(title, body, reminder.key);
    addToast(
      <ToasterItem type="info" closeButton>
        <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <strong>{title}</strong>
          <span>{body}</span>
        </span>
      </ToasterItem>,
      { autoClose: 15000 },
    );
  }, []);

  const tick = useCallback(() => {
    const now = Date.now();
    const due = collectDueReminders(upcomingRef.current, now, BACKFILL_MS);
    let changed = false;
    for (const reminder of due) {
      if (firedRef.current.has(reminder.key)) continue;
      fire(reminder);
      firedRef.current.set(reminder.key, now);
      changed = true;
    }
    if (changed) saveFiredReminders(firedRef.current);
  }, [fire]);

  const fetchUpcoming = useCallback(async () => {
    const urls = [...visibleCalendarUrls];
    if (urls.length === 0) {
      upcomingRef.current = [];
      return;
    }
    const now = Date.now();
    const timeRange = {
      start: new Date(now - BACKFILL_MS),
      end: new Date(now + LOOKAHEAD_MS),
    };

    const fetchCalendar = async (url: string) => {
      // Expanded gives correct per-occurrence start times; non-expanded
      // preserves the master's VALARM (sabre/vobject drops alarms from
      // expanded instances). Merge the two so recurring reminders fire.
      const [expanded, masters] = await Promise.all([
        caldavService
          .fetchEvents(url, { timeRange, expand: true })
          .then((res) => (res.success && res.data ? res.data : []))
          .catch(() => []),
        caldavService
          .fetchEvents(url, { timeRange, expand: false })
          .then((res) => (res.success && res.data ? res.data : []))
          .catch(() => []),
      ]);

      const alarmsByUid = buildAlarmMap(masters.flatMap((ce) => ce.data.events ?? []));
      const instances = expanded.flatMap((ce) =>
        (ce.data.events ?? []).map((event) => ({ event, calendarUrl: ce.calendarUrl })),
      );
      return withMasterAlarms(instances, alarmsByUid);
    };

    const results = await Promise.all(urls.map(fetchCalendar));
    upcomingRef.current = results.flat().filter(({ event }) => event.alarms?.length);
  }, [caldavService, visibleCalendarUrls]);

  useEffect(() => {
    if (!isConnected) return;
    let cancelled = false;

    const refetchAndEvaluate = async () => {
      await fetchUpcoming();
      if (!cancelled) tick();
    };

    void refetchAndEvaluate();
    const fetchTimer = setInterval(() => void refetchAndEvaluate(), FETCH_INTERVAL_MS);
    const tickTimer = setInterval(tick, TICK_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(fetchTimer);
      clearInterval(tickTimer);
    };
  }, [isConnected, fetchUpcoming, tick]);
};
