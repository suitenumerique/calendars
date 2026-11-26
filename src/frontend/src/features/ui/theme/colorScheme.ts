export type ColorScheme = "system" | "light" | "dark";

export type ColorVariant = "light" | "dark";

export const COLOR_SCHEME_KEY = "calendars-color-scheme";

const COLOR_SCHEMES: readonly string[] = ["system", "light", "dark"];

/**
 * Read the color scheme the user selected in this browser.
 * Return "system" when the value is absent, unknown or not available.
 */
export const loadColorScheme = (): ColorScheme => {
  try {
    const stored = localStorage.getItem(COLOR_SCHEME_KEY);
    if (stored && COLOR_SCHEMES.includes(stored)) return stored as ColorScheme;
  } catch {
    // Ignore storage errors
  }
  return "system";
};

export const saveColorScheme = (scheme: ColorScheme) => {
  try {
    localStorage.setItem(COLOR_SCHEME_KEY, scheme);
  } catch {
    // Ignore storage errors
  }
};

export const resolveVariant = (scheme: ColorScheme, systemPrefersDark: boolean): ColorVariant => {
  if (scheme !== "system") return scheme;
  return systemPrefersDark ? "dark" : "light";
};
