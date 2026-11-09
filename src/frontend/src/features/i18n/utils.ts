export const splitLocaleCode = (language: string) => {
  const locale = language.split(/[-_]/);
  return {
    language: locale[0],
    region: locale.length === 2 ? locale[1] : undefined,
  };
};

export const capitalizeRegion = (language: string) => {
  const { language: lang, region } = splitLocaleCode(language);
  return lang + (region ? "-" + region.toUpperCase() : "");
};

const CUNNINGHAM_LOCALES: Record<string, string> = {
  en: "en-US",
  fr: "fr-FR",
  nl: "nl-NL",
};

/** UI kit locale for a language code. The UI kit only knows full codes such as "fr-FR". */
export const toCunninghamLocale = (language: string) =>
  CUNNINGHAM_LOCALES[splitLocaleCode(language).language.toLowerCase()] ??
  capitalizeRegion(language);

export type PickerLanguage = { label: string; value: string; shortLabel: string };

/** Name of a language in that language, for example "français" for "fr". */
const nativeName = (language: string, fallback: string) => {
  try {
    const name = new Intl.DisplayNames([language], { type: "language" }).of(language);
    return name ? name.charAt(0).toLocaleUpperCase(language) + name.slice(1) : fallback;
  } catch {
    return fallback;
  }
};

const toPickerLanguage = (value: string, name: string): PickerLanguage => {
  const { language } = splitLocaleCode(value);
  return { value, label: nativeName(language, name), shortLabel: language.toUpperCase() };
};

/**
 * Picker entries for the configured languages that have translations.
 * The configured names are in English, so each label is the native name.
 */
export const getPickerLanguages = (
  configured: [string, string][],
  translated: string[],
): PickerLanguage[] =>
  configured
    .filter(([value]) => translated.includes(splitLocaleCode(value).language))
    .map(([value, name]) => toPickerLanguage(value, name));

/**
 * Picker value to check: the user language, or else the value with the same
 * language subtag as the UI language. A user without a saved language sees
 * the UI in the detected language, so the picker must show that language.
 * The picker ignores a saved language that it does not offer.
 */
export const getPickerLanguage = (
  userLanguage: string | null | undefined,
  uiLanguage: string,
  values: string[],
): string | undefined => {
  if (userLanguage && values.includes(userLanguage)) return userLanguage;
  const language = splitLocaleCode(uiLanguage).language.toLowerCase();
  return values.find((value) => splitLocaleCode(value).language === language);
};

/**
 * Picker options, with the language of the UI checked. When the offered
 * languages do not include the UI language, an option for the UI language
 * comes first. Without a checked option, the UI kit shows its first option
 * as the current language.
 */
export const getPickerOptions = (
  offered: PickerLanguage[],
  userLanguage: string | null | undefined,
  uiLanguage: string,
): (PickerLanguage & { isChecked: boolean })[] => {
  const checked = getPickerLanguage(
    userLanguage,
    uiLanguage,
    offered.map(({ value }) => value),
  );
  const options = offered.map((language) => ({
    ...language,
    isChecked: language.value === checked,
  }));
  if (checked) return options;
  return [{ ...toPickerLanguage(uiLanguage, uiLanguage), isChecked: true }, ...options];
};
