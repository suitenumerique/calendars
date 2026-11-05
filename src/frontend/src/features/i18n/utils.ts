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

/**
 * Picker value to check: the user language, or else the value with the same
 * language subtag as the UI language. A user without a saved language sees
 * the UI in the detected language, so the picker must show that language.
 */
export const getPickerLanguage = (
  userLanguage: string | null | undefined,
  uiLanguage: string,
  values: string[],
): string | undefined => {
  if (userLanguage) return userLanguage;
  const language = splitLocaleCode(uiLanguage).language.toLowerCase();
  return values.find((value) => splitLocaleCode(value).language === language);
};
