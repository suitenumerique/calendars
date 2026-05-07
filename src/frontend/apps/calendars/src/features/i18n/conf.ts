export const LANGUAGES_ALLOWED = ["en-us", "fr-fr"];
export const LANGUAGE_LOCAL_STORAGE = "main-language";
export const BASE_LANGUAGE =
  process.env.NEXT_PUBLIC_DEFAULT_LANGUAGE || LANGUAGES_ALLOWED[0];
export const IS_LANGUAGE_FORCED =
  process.env.NEXT_PUBLIC_FORCED_DEFAULT_LANGUAGE === "true";
