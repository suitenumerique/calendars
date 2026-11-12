/**
 * Thin wrapper around the Web Notifications API. Every entry point is
 * guarded so the rest of the app can call these unconditionally, even in
 * non-browser (test / SSR) environments or when the user denied access.
 */

const NOTIFICATION_ICON = "/favicon.png";

export const isNotificationSupported = (): boolean =>
  typeof window !== "undefined" && "Notification" in window;

/**
 * Ask for permission once. Resolves to the resulting (or already-decided)
 * permission. Never throws — a rejected promise from older browsers is
 * swallowed and the current permission is returned.
 */
export const ensureNotificationPermission = async (): Promise<NotificationPermission> => {
  if (!isNotificationSupported()) return "denied";
  if (Notification.permission !== "default") return Notification.permission;
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
};

/**
 * Show a desktop notification. Returns true if one was actually shown.
 * `tag` collapses duplicates at the OS level as a second line of defence
 * on top of our own fired-reminder bookkeeping.
 */
export const showBrowserNotification = (title: string, body: string, tag?: string): boolean => {
  if (!isNotificationSupported() || Notification.permission !== "granted") return false;
  try {
    new Notification(title, { body, tag, icon: NOTIFICATION_ICON });
    return true;
  } catch {
    return false;
  }
};
