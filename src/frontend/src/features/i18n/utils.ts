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

type PickerLanguage = { label: string; value: string; shortLabel: string };

/**
 * Primary subtag of a language code, in lowercase.
 * The case of a language code has no meaning.
 */
const primarySubtag = (language: string) => splitLocaleCode(language).language.toLowerCase();

/**
 * Native name of a language, with a capital first letter.
 * Returns the fallback when Intl has no name for the language.
 */
const nativeName = (language: string, fallback: string) => {
  try {
    const name = new Intl.DisplayNames([language], { type: "language", fallback: "none" }).of(
      language,
    );
    return name ? name.charAt(0).toLocaleUpperCase(language) + name.slice(1) : fallback;
  } catch {
    return fallback;
  }
};

const toPickerLanguage = (value: string, name: string): PickerLanguage => {
  const language = primarySubtag(value);
  return { value, label: nativeName(language, name), shortLabel: language.toUpperCase() };
};

/**
 * Picker entries for the configured languages that have translations, in
 * the config order. Each label is the native name of the language. When Intl
 * has no native name, the label is the configured name.
 */
export const getPickerLanguages = (
  configured: [string, string][],
  translated: string[],
): PickerLanguage[] =>
  configured
    .filter(([value]) => translated.includes(primarySubtag(value)))
    .map(([value, name]) => toPickerLanguage(value, name));

/**
 * Picker value to check. It is the saved language of the user when the
 * values include it. If not, it is the value with the same primary subtag as
 * the UI language. It is undefined when no value matches.
 */
export const getPickerLanguage = (
  userLanguage: string | null | undefined,
  uiLanguage: string,
  values: string[],
): string | undefined => {
  if (userLanguage && values.includes(userLanguage)) return userLanguage;
  const language = primarySubtag(uiLanguage);
  return values.find((value) => primarySubtag(value) === language);
};

/**
 * Picker options with one option checked. The checked option is the saved
 * language when it is offered. If not, it is the offered language that
 * matches the UI language. When no offered language matches, a checked
 * option for the UI language comes first. Without it, the UI kit shows the
 * first offered language as the current language.
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
