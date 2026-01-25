/**
 * Hook for calendar locale management
 *
 * Provides locale-aware utilities for date formatting and calendar configuration
 */
import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { enUS, fr, nl, Locale } from 'date-fns/locale';

// Map i18n language codes to date-fns locales
const DATE_FNS_LOCALES: Record<string, Locale> = {
  en: enUS,
  'en-us': enUS,
  'en-US': enUS,
  fr: fr,
  'fr-fr': fr,
  'fr-FR': fr,
  nl: nl,
  'nl-nl': nl,
  'nl-NL': nl,
};

// Map i18n language codes to Intl locale codes
const INTL_LOCALES: Record<string, string> = {
  en: 'en-US',
  'en-us': 'en-US',
  'en-US': 'en-US',
  fr: 'fr-FR',
  'fr-fr': 'fr-FR',
  'fr-FR': 'fr-FR',
  nl: 'nl-NL',
  'nl-nl': 'nl-NL',
  'nl-NL': 'nl-NL',
};

// First day of week by locale (0 = Sunday, 1 = Monday)
const FIRST_DAY_OF_WEEK: Record<string, 0 | 1 | 2 | 3 | 4 | 5 | 6> = {
  en: 0,        // US: Sunday
  'en-us': 0,
  'en-US': 0,
  fr: 1,        // France: Monday
  'fr-fr': 1,
  'fr-FR': 1,
  nl: 1,        // Netherlands: Monday
  'nl-nl': 1,
  'nl-NL': 1,
};

export function useCalendarLocale() {
  const { i18n, t } = useTranslation();
  const currentLanguage = i18n.language;

  // Get date-fns locale
  const dateFnsLocale = useMemo(() => {
    return DATE_FNS_LOCALES[currentLanguage] || DATE_FNS_LOCALES['en'] || enUS;
  }, [currentLanguage]);

  // Get Intl locale string (e.g., 'fr-FR')
  const intlLocale = useMemo(() => {
    return INTL_LOCALES[currentLanguage] || INTL_LOCALES['en'] || 'en-US';
  }, [currentLanguage]);

  // Get calendar library locale code
  const calendarLocale = useMemo(() => {
    const base = currentLanguage.split('-')[0];
    return base || 'en';
  }, [currentLanguage]);

  // Get first day of week for this locale
  const firstDayOfWeek = useMemo(() => {
    return FIRST_DAY_OF_WEEK[currentLanguage] ?? FIRST_DAY_OF_WEEK['en'] ?? 0;
  }, [currentLanguage]);

  // Format date using Intl.DateTimeFormat with current locale
  const formatDate = useCallback((
    date: Date | string,
    options?: Intl.DateTimeFormatOptions
  ): string => {
    const d = typeof date === 'string' ? new Date(date) : date;
    return new Intl.DateTimeFormat(intlLocale, options).format(d);
  }, [intlLocale]);

  // Format time using Intl.DateTimeFormat with current locale
  const formatTime = useCallback((
    date: Date | string,
    options?: Intl.DateTimeFormatOptions
  ): string => {
    const d = typeof date === 'string' ? new Date(date) : date;
    return new Intl.DateTimeFormat(intlLocale, {
      hour: 'numeric',
      minute: 'numeric',
      ...options,
    }).format(d);
  }, [intlLocale]);

  // Format day header for calendar views
  const formatDayHeader = useCallback((date: Date): { html: string } => {
    const dayOfWeek = date.toLocaleDateString(intlLocale, { weekday: 'short' });
    const dayOfMonth = date.toLocaleDateString(intlLocale, { day: 'numeric' });
    return {
      html: `<div class="day-header"><span class="day-of-month">${dayOfMonth}</span> <span class="day-of-week">${dayOfWeek}</span></div>`,
    };
  }, [intlLocale]);

  // Get calendar translations for the library
  const getCalendarTranslations = useCallback(() => ({
    dayGridMonth: t('calendar.views.month'),
    dayGridWeek: t('calendar.views.week'),
    dayGridDay: t('calendar.views.day'),
    timeGridWeek: t('calendar.views.week'),
    timeGridDay: t('calendar.views.day'),
    listDay: t('calendar.views.listDay'),
    listWeek: t('calendar.views.listWeek'),
    listMonth: t('calendar.views.listMonth'),
    listYear: t('calendar.views.listYear'),
    today: t('calendar.views.today'),
  }), [t]);

  return {
    // Locales
    dateFnsLocale,
    intlLocale,
    calendarLocale,
    currentLanguage,

    // Calendar settings
    firstDayOfWeek,

    // Formatters
    formatDate,
    formatTime,
    formatDayHeader,

    // Translations
    getCalendarTranslations,
    t,
  };
}

export type CalendarLocale = ReturnType<typeof useCalendarLocale>;
