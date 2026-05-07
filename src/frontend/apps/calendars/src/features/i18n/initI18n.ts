import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import {
  BASE_LANGUAGE,
  IS_LANGUAGE_FORCED,
  LANGUAGES_ALLOWED,
  LANGUAGE_LOCAL_STORAGE,
} from "./conf";
import resources from "./translations.json";

/**
 * How language works:
 *
 * - First visit on the website, the user is not logged in, we detect the browser current language with LanguageDetector
 * - When the user logs in, its language attribute is null
 * - Because the user language is null, we use the language detected by LanguageDetector
 * - If the user changes the language via the language picker, we update the language of the user via a request to the backend
 * - When the user object is fetched/refreshed, LanguagePickerUserMenu syncs user.language back into i18next (see Header.tsx)
 *
 * This way we ensure that we use the most probable language of the user.
 */

const syncLanguageToDom = (lng: string) => {
  if (typeof window === "undefined") return;
  document.documentElement.setAttribute("lang", lng);
  localStorage.setItem(LANGUAGE_LOCAL_STORAGE, lng);
};

// Fires on subsequent changes (picker, user.language sync).
i18n.on("languageChanged", syncLanguageToDom);

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: BASE_LANGUAGE,
    detection: {
      order: IS_LANGUAGE_FORCED ? ["cookie"] : ["cookie", "navigator"],
      caches: ["cookie"],
      lookupCookie: "calendars_language",
      cookieMinutes: 525600,
      cookieOptions: {
        path: "/",
        sameSite: "lax",
      },
    },
    interpolation: {
      escapeValue: false,
    },
    showSupportNotice: false,
    preload: LANGUAGES_ALLOWED,
  })
  .then(() => syncLanguageToDom(i18n.language))
  .catch(() => {
    throw new Error("i18n initialization failed");
  });

export default i18n;
