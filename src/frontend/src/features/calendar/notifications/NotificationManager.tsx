import { useEventReminders } from "./useEventReminders";

/**
 * Headless component that runs the event-reminder poller for as long as it
 * is mounted. Render it once inside the authenticated calendar tree.
 */
export const NotificationManager = () => {
  useEventReminders();
  return null;
};
