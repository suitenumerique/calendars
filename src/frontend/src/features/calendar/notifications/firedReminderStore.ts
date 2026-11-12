/**
 * localStorage-backed record of reminders we've already fired, so a page
 * reload (or a second tab) doesn't replay a notification the user has
 * already seen. Entries are pruned past a retention window to keep the
 * blob small.
 */

const STORAGE_KEY = "calendar-fired-reminders";
// Must exceed the poller's lookahead window so a fired key isn't pruned
// while its event is still being polled (which would let it re-fire).
const RETENTION_MS = 9 * 86_400_000; // 9 days

type StoredMap = Record<string, number>; // reminderKey -> firedAt (ms)

/** Load the fired-reminder keys, dropping any older than the retention window. */
export const loadFiredReminders = (nowMs: number): Map<string, number> => {
  const map = new Map<string, number>();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return map;
    const stored = JSON.parse(raw) as StoredMap;
    for (const [key, firedAt] of Object.entries(stored)) {
      if (typeof firedAt === "number" && nowMs - firedAt < RETENTION_MS) {
        map.set(key, firedAt);
      }
    }
  } catch {
    // Corrupt / unavailable storage — start clean.
  }
  return map;
};

/** Persist the fired-reminder keys, best-effort. */
export const saveFiredReminders = (map: Map<string, number>): void => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(map)));
  } catch {
    // Quota / unavailable storage — ignore; in-memory set still dedups
    // for this session.
  }
};
