const LAST_VIEW_KEY = "calendar-last-view";

const DEFAULT_VIEW = "timeGridWeek";

/** View ids the desktop toolbar offers. */
const DESKTOP_VIEWS = [
  "timeGridDay",
  "timeGridWorkWeek",
  "timeGridWeek",
  "dayGridMonth",
  "listWeek",
];

/**
 * Read the view the user last selected in this browser.
 * Return the week view when the value is absent or unknown.
 * Return the week view also when storage is not available.
 */
export const loadLastView = (): string => {
  try {
    const stored = localStorage.getItem(LAST_VIEW_KEY);
    if (stored && DESKTOP_VIEWS.includes(stored)) return stored;
  } catch {
    // Ignore storage errors
  }
  return DEFAULT_VIEW;
};

export const saveLastView = (view: string) => {
  try {
    localStorage.setItem(LAST_VIEW_KEY, view);
  } catch {
    // Ignore storage errors
  }
};
