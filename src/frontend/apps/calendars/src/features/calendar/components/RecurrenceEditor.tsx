import { Select, Input } from '@gouvfr-lasuite/cunningham-react';
import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { IcsRecurrenceRule, IcsWeekDay } from 'ts-ics';

type RecurrenceFrequency = IcsRecurrenceRule['frequency'];

const WEEKDAY_KEYS: IcsWeekDay[] = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];

const MONTHS = [
  { value: 1, key: 'january' },
  { value: 2, key: 'february' },
  { value: 3, key: 'march' },
  { value: 4, key: 'april' },
  { value: 5, key: 'may' },
  { value: 6, key: 'june' },
  { value: 7, key: 'july' },
  { value: 8, key: 'august' },
  { value: 9, key: 'september' },
  { value: 10, key: 'october' },
  { value: 11, key: 'november' },
  { value: 12, key: 'december' },
];

interface RecurrenceEditorProps {
  value?: IcsRecurrenceRule;
  onChange: (rule: IcsRecurrenceRule | undefined) => void;
}

/**
 * Validate day of month based on month (handles leap years and month lengths)
 */
function isValidDayForMonth(day: number, month?: number): boolean {
  if (day < 1 || day > 31) return false;

  if (!month) return true; // No month specified, allow any valid day

  // Days per month (non-leap year)
  const daysInMonth: Record<number, number> = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31
  };

  return day <= (daysInMonth[month] || 31);
}

/**
 * Get warning message for invalid dates
 */
function getDateWarning(t: (key: string) => string, day: number, month?: number): string | null {
  if (!month) return null;

  if (month === 2 && day > 29) {
    return t('calendar.recurrence.warnings.februaryMax');
  }
  if (month === 2 && day === 29) {
    return t('calendar.recurrence.warnings.leapYear');
  }
  if ([4, 6, 9, 11].includes(month) && day > 30) {
    return t('calendar.recurrence.warnings.monthMax30');
  }
  if (day > 31) {
    return t('calendar.recurrence.warnings.dayMax31');
  }

  return null;
}

export function RecurrenceEditor({ value, onChange }: RecurrenceEditorProps) {
  const { t } = useTranslation();

  const [isCustom, setIsCustom] = useState(() => {
    if (!value) return false;
    return value.interval !== 1 || value.byDay?.length || value.byMonthday?.length || value.byMonth?.length || value.count || value.until;
  });

  // Generate options from translations
  const recurrenceOptions = useMemo(() => [
    { value: 'NONE', label: t('calendar.recurrence.none') },
    { value: 'DAILY', label: t('calendar.recurrence.daily') },
    { value: 'WEEKLY', label: t('calendar.recurrence.weekly') },
    { value: 'MONTHLY', label: t('calendar.recurrence.monthly') },
    { value: 'YEARLY', label: t('calendar.recurrence.yearly') },
    { value: 'CUSTOM', label: t('calendar.recurrence.custom') },
  ], [t]);

  const frequencyOptions = useMemo(() => [
    { value: 'DAILY', label: t('calendar.recurrence.days') },
    { value: 'WEEKLY', label: t('calendar.recurrence.weeks') },
    { value: 'MONTHLY', label: t('calendar.recurrence.months') },
    { value: 'YEARLY', label: t('calendar.recurrence.years') },
  ], [t]);

  const weekdays = useMemo(() => WEEKDAY_KEYS.map(key => ({
    value: key,
    label: t(`calendar.recurrence.weekdays.${key.toLowerCase()}`),
  })), [t]);

  const monthOptions = useMemo(() => MONTHS.map(month => ({
    value: String(month.value),
    label: t(`calendar.recurrence.months.${month.key}`),
  })), [t]);

  const getSimpleValue = (): string => {
    if (!value) return 'NONE';
    if (isCustom) return 'CUSTOM';
    return value.frequency;
  };

  const handleSimpleChange = (newValue: string) => {
    if (newValue === 'NONE') {
      setIsCustom(false);
      onChange(undefined);
      return;
    }

    if (newValue === 'CUSTOM') {
      setIsCustom(true);
      onChange({
        frequency: 'WEEKLY',
        interval: 1
      });
      return;
    }

    setIsCustom(false);
    onChange({
      frequency: newValue as RecurrenceFrequency,
      interval: 1,
      byDay: undefined,
      byMonthday: undefined,
      byMonth: undefined,
      count: undefined,
      until: undefined
    });
  };

  const handleChange = (updates: Partial<IcsRecurrenceRule>) => {
    onChange({
      frequency: 'WEEKLY',
      interval: 1,
      ...value,
      ...updates
    });
  };

  // Get selected day strings from byDay array
  const getSelectedDays = (): IcsWeekDay[] => {
    if (!value?.byDay) return [];
    return value.byDay.map(d => typeof d === 'string' ? d as IcsWeekDay : d.day);
  };

  const isDaySelected = (day: IcsWeekDay): boolean => {
    return getSelectedDays().includes(day);
  };

  const toggleDay = (day: IcsWeekDay) => {
    const currentDays = getSelectedDays();
    const newDays = currentDays.includes(day)
      ? currentDays.filter(d => d !== day)
      : [...currentDays, day];
    handleChange({ byDay: newDays.map(d => ({ day: d })) });
  };

  // Get selected month day
  const getMonthDay = (): number => {
    return value?.byMonthday?.[0] ?? 1;
  };

  // Get selected month for yearly recurrence
  const getMonth = (): string => {
    return String(value?.byMonth?.[0] ?? 1);
  };

  const handleMonthDayChange = (day: number) => {
    handleChange({ byMonthday: [day] });
  };

  const handleMonthChange = (month: number) => {
    handleChange({ byMonth: [month] });
  };

  // Calculate date warning
  const monthDay = getMonthDay();
  const selectedMonth = value?.frequency === 'YEARLY' ? parseInt(getMonth()) : undefined;
  const dateWarning = isCustom && (value?.frequency === 'MONTHLY' || value?.frequency === 'YEARLY')
    ? getDateWarning(t, monthDay, selectedMonth)
    : null;

  return (
    <div className="recurrence-editor-layout recurrence-editor-layout--gap-1rem">
      <Select
        label={t('calendar.recurrence.label')}
        value={getSimpleValue()}
        options={recurrenceOptions}
        onChange={(e) => handleSimpleChange(String(e.target.value ?? ''))}
        fullWidth
      />

      {isCustom && (
        <div className="recurrence-editor-layout recurrence-editor-layout--gap-1rem recurrence-editor-layout--margin-left-2rem">
          <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-1rem">
            <span>{t('calendar.recurrence.everyLabel')}</span>
            <Input
              label=""
              type="number"
              min={1}
              value={value?.interval || 1}
              onChange={(e) => handleChange({ interval: parseInt(e.target.value) || 1 })}
            />
            <Select
              label=""
              value={value?.frequency || 'WEEKLY'}
              options={frequencyOptions}
              onChange={(e) => handleChange({ frequency: String(e.target.value ?? '') as RecurrenceFrequency })}
            />
          </div>

          {/* WEEKLY: Day selection */}
          {value?.frequency === 'WEEKLY' && (
            <div className="recurrence-editor-layout">
              <span className="recurrence-editor__label">{t('calendar.recurrence.repeatOn')}</span>
              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--gap-0-5rem recurrence-editor-layout--margin-top-0-5rem recurrence-editor-layout--flex-wrap">
                {weekdays.map(day => {
                  const isSelected = isDaySelected(day.value);
                  return (
                    <button
                      key={day.value}
                      type="button"
                      className={`recurrence-editor__weekday-button ${isSelected ? 'recurrence-editor__weekday-button--selected' : ''}`}
                      onClick={(e) => {
                        e.preventDefault();
                        toggleDay(day.value);
                      }}
                    >
                      {day.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* MONTHLY: Day of month selection */}
          {value?.frequency === 'MONTHLY' && (
            <div className="recurrence-editor-layout">
              <span className="recurrence-editor__label">{t('calendar.recurrence.repeatOnDay')}</span>
              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-0-5rem recurrence-editor-layout--margin-top-0-5rem">
                <span>{t('calendar.recurrence.dayOfMonth')}</span>
                <Input
                  label=""
                  type="number"
                  min={1}
                  max={31}
                  value={getMonthDay()}
                  onChange={(e) => {
                    const day = parseInt(e.target.value) || 1;
                    if (day >= 1 && day <= 31) {
                      handleMonthDayChange(day);
                    }
                  }}
                    />
              </div>
              {dateWarning && (
                <div className="recurrence-editor__warning">
                  ⚠️ {dateWarning}
                </div>
              )}
            </div>
          )}

          {/* YEARLY: Month + Day selection */}
          {value?.frequency === 'YEARLY' && (
            <div className="recurrence-editor-layout">
              <span className="recurrence-editor__label">{t('calendar.recurrence.repeatOnDate')}</span>
              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-0-5rem recurrence-editor-layout--margin-top-0-5rem">
                <Select
                  label=""
                  value={getMonth()}
                  options={monthOptions}
                  onChange={(e) => handleMonthChange(parseInt(String(e.target.value)) || 1)}
                />
                <Input
                  label=""
                  type="number"
                  min={1}
                  max={31}
                  value={getMonthDay()}
                  onChange={(e) => {
                    const day = parseInt(e.target.value) || 1;
                    if (day >= 1 && day <= 31) {
                      handleMonthDayChange(day);
                    }
                  }}
                    />
              </div>
              {dateWarning && (
                <div className="recurrence-editor__warning">
                  ⚠️ {dateWarning}
                </div>
              )}
            </div>
          )}

          {/* End conditions */}
          <div className="recurrence-editor-layout">
            <span className="recurrence-editor__label">{t('calendar.recurrence.endsLabel')}</span>
            <div className="recurrence-editor-layout recurrence-editor-layout--gap-0-5rem recurrence-editor-layout--margin-top-0-5rem">
              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-0-5rem">
                <input
                  type="radio"
                  id="end-never"
                  name="end-type"
                  checked={!value?.count && !value?.until}
                  onChange={() => handleChange({ count: undefined, until: undefined })}
                />
                <label htmlFor="end-never">{t('calendar.recurrence.never')}</label>
              </div>

              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-0-5rem">
                <input
                  type="radio"
                  id="end-date"
                  name="end-type"
                  checked={!!value?.until}
                  onChange={() => handleChange({ until: { type: 'DATE', date: new Date() }, count: undefined })}
                />
                <label htmlFor="end-date">{t('calendar.recurrence.on')}</label>
                {value?.until && (
                  <Input
                    label=""
                    type="date"
                    value={value.until.date instanceof Date ? value.until.date.toISOString().split('T')[0] : ''}
                    onChange={(e) => handleChange({
                      until: {
                        type: 'DATE',
                        date: new Date(e.target.value),
                      }
                    })}
                  />
                )}
              </div>

              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-0-5rem">
                <input
                  type="radio"
                  id="end-count"
                  name="end-type"
                  checked={!!value?.count}
                  onChange={() => handleChange({ count: 10, until: undefined })}
                />
                <label htmlFor="end-count">{t('calendar.recurrence.after')}</label>
                {value?.count !== undefined && (
                  <>
                    <Input
                      label=""
                      type="number"
                      min={1}
                      value={value.count}
                      onChange={(e) => handleChange({ count: parseInt(e.target.value) || 1 })}
                            />
                    <span>{t('calendar.recurrence.occurrences')}</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
