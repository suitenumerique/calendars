import { Alert, Input, Select, VariantType } from "@gouvfr-lasuite/cunningham-react";
import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { FOREVER_YEARS_THRESHOLD } from "../../services/dav/constants";
import { Warning } from "@gouvfr-lasuite/ui-kit/icons";

import type { IcsRecurrenceRule, IcsWeekDay } from "ts-ics";

const SECONDS_PER_YEAR = 86400 * 365;
const FOREVER_THRESHOLD_SECS = FOREVER_YEARS_THRESHOLD * SECONDS_PER_YEAR;

const FREQ_SECONDS: Record<string, number> = {
  YEARLY: SECONDS_PER_YEAR,
  MONTHLY: 86400 * 30,
  WEEKLY: 86400 * 7,
  DAILY: 86400,
  HOURLY: 3600,
  MINUTELY: 60,
  SECONDLY: 1,
};

type RecurrenceFrequency = IcsRecurrenceRule["frequency"];
type EndType = "never" | "count" | "date";

const WEEKDAY_KEYS: IcsWeekDay[] = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];

const MONTHS = [
  { value: 1, key: "january" },
  { value: 2, key: "february" },
  { value: 3, key: "march" },
  { value: 4, key: "april" },
  { value: 5, key: "may" },
  { value: 6, key: "june" },
  { value: 7, key: "july" },
  { value: 8, key: "august" },
  { value: 9, key: "september" },
  { value: 10, key: "october" },
  { value: 11, key: "november" },
  { value: 12, key: "december" },
];

const ADVANCED_RRULE_KEYS: (keyof IcsRecurrenceRule)[] = ["bySetPos", "byYearday", "byWeekNo"];

function hasAdvancedProperties(rule?: IcsRecurrenceRule): boolean {
  if (!rule) return false;
  return ADVANCED_RRULE_KEYS.some((key) => rule[key] !== undefined && rule[key] !== null);
}

function getAdvancedProperties(rule?: IcsRecurrenceRule): Partial<IcsRecurrenceRule> {
  if (!rule) return {};
  const result: Partial<IcsRecurrenceRule> = {};
  for (const key of ADVANCED_RRULE_KEYS) {
    if (rule[key] !== undefined && rule[key] !== null) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (result as any)[key] = rule[key];
    }
  }
  return result;
}

interface RecurrenceEditorProps {
  value?: IcsRecurrenceRule;
  onChange: (rule: IcsRecurrenceRule | undefined) => void;
}

// Yearly recurrence only — when the user picks a specific month + day,
// warn if that combination is invalid or only valid in leap years.
// Monthly recurrence does NOT show warnings: the same day-of-month is
// applied to every month and the user gets to choose how the calendar
// handles short months at the iCal level.
//
// TODO: restore proper monthly warnings. When the user picks a
// day-of-month >= 29 with MONTHLY recurrence, we should warn that some
// months will be skipped (day=29 → non-leap Februaries, day=30 → all
// Februaries, day=31 → April/June/Sep/Nov). The original yearly-context
// translation strings (``februaryMax``, ``leapYear``, ``monthMax30``)
// don't quite fit the monthly framing — they read like "this month"
// references a single month — so doing this properly requires a new
// set of monthly-specific copy keys, not just reusing the existing
// ones.
function getDateWarning(t: (key: string) => string, day: number, month?: number): string | null {
  if (!month) return null;

  if (month === 2 && day > 29) {
    return t("calendar.recurrence.warnings.februaryMax");
  }
  if (month === 2 && day === 29) {
    return t("calendar.recurrence.warnings.leapYear");
  }
  if ([4, 6, 9, 11].includes(month) && day > 30) {
    return t("calendar.recurrence.warnings.monthMax30");
  }
  if (day > 31) {
    return t("calendar.recurrence.warnings.dayMax31");
  }

  return null;
}

export function isForeverCount(rule: IcsRecurrenceRule): boolean {
  if (!rule.count) return false;
  const stepSecs = FREQ_SECONDS[rule.frequency];
  if (!stepSecs) return false;
  const interval = rule.interval ?? 1;
  return rule.count * interval * stepSecs > FOREVER_THRESHOLD_SECS;
}

// `IcsDateObject` carries both `date` (real UTC) and `local.date`
// (TZID-stripped "fake UTC"). When TZID is present, `local.date` is
// the authoritative wall-clock instant; otherwise fall back to
// `date`. Used by every UNTIL-reading path so classification and
// rendering agree on the same resolved Date.
export function getResolvedUntilDate(rule: IcsRecurrenceRule): Date | undefined {
  const date = rule.until?.local?.date ?? rule.until?.date;
  return date instanceof Date ? date : undefined;
}

export function isForeverUntil(rule: IcsRecurrenceRule): boolean {
  const date = getResolvedUntilDate(rule);
  if (!date) return false;
  return date.getTime() - Date.now() > FOREVER_THRESHOLD_SECS * 1000;
}

export function getEndType(value?: IcsRecurrenceRule): EndType {
  if (value?.count) {
    return isForeverCount(value) ? "never" : "count";
  }
  if (value?.until) {
    return isForeverUntil(value) ? "never" : "date";
  }
  return "never";
}

export function RecurrenceEditor({ value, onChange }: RecurrenceEditorProps) {
  const { t } = useTranslation();

  const [isCustom, setIsCustom] = useState(() => {
    if (!value) return false;
    const userCount = value.count && !isForeverCount(value) ? value.count : undefined;
    const userUntil = value.until && !isForeverUntil(value) ? value.until : undefined;
    return !!(
      value.interval !== 1 ||
      value.byDay?.length ||
      value.byMonthday?.length ||
      value.byMonth?.length ||
      userCount ||
      userUntil
    );
  });

  const recurrenceOptions = useMemo(
    () => [
      { value: "NONE", label: t("calendar.recurrence.none") },
      { value: "DAILY", label: t("calendar.recurrence.daily") },
      { value: "WEEKLY", label: t("calendar.recurrence.weekly") },
      { value: "MONTHLY", label: t("calendar.recurrence.monthly") },
      { value: "YEARLY", label: t("calendar.recurrence.yearly") },
      { value: "CUSTOM", label: t("calendar.recurrence.custom") },
    ],
    [t],
  );

  const frequencyOptions = useMemo(
    () => [
      { value: "DAILY", label: t("calendar.recurrence.days") },
      { value: "WEEKLY", label: t("calendar.recurrence.weeks") },
      { value: "MONTHLY", label: t("calendar.recurrence.months") },
      { value: "YEARLY", label: t("calendar.recurrence.years") },
    ],
    [t],
  );

  const weekdays = useMemo(
    () =>
      WEEKDAY_KEYS.map((key) => ({
        value: key,
        label: t(`calendar.recurrence.weekdays.${key.toLowerCase()}`),
      })),
    [t],
  );

  const monthOptions = useMemo(
    () =>
      MONTHS.map((month) => ({
        value: String(month.value),
        label: t(`calendar.recurrence.monthNames.${month.key}`),
      })),
    [t],
  );

  const summary = useMemo((): string => {
    if (!isCustom || !value) return "";

    const interval = value.interval || 1;
    const freq = value.frequency;
    const freqLabel = t(
      `calendar.recurrence.${freq === "DAILY" ? "days" : freq === "WEEKLY" ? "weeks" : freq === "MONTHLY" ? "months" : "years"}`,
    );

    let result = `${t("calendar.recurrence.everyLabel")} ${interval > 1 ? `${interval} ` : ""}${freqLabel}`;

    if (freq === "WEEKLY" && value.byDay?.length) {
      const dayLabels = value.byDay.map((d) => {
        const dayKey = typeof d === "string" ? d : d.day;
        return t(`calendar.recurrence.weekdays.${dayKey.toLowerCase()}`);
      });
      result += ` · ${dayLabels.join(", ")}`;
    }

    // Defer to ``getEndType``: a ``count`` / ``until`` past the
    // forever threshold classifies as ``never`` and must not show
    // a date / count fragment, otherwise the summary contradicts
    // the active end-of-recurrence button.
    const summaryEndType = getEndType(value);
    if (summaryEndType === "date" && value.until) {
      const untilDate = getResolvedUntilDate(value);
      const dateStr = untilDate ? untilDate.toISOString().split("T")[0] : "";
      result += ` · ${t("calendar.recurrence.on")} ${dateStr}`;
    } else if (summaryEndType === "count" && value.count) {
      result += ` · ${value.count} ${t("calendar.recurrence.occurrences")}`;
    }

    return result;
  }, [isCustom, value, t]);

  const getSimpleValue = (): string => {
    if (!value) return "NONE";
    if (isCustom) return "CUSTOM";
    return value.frequency;
  };

  const handleSimpleChange = (newValue: string) => {
    if (newValue === "NONE") {
      setIsCustom(false);
      onChange(undefined);
      return;
    }

    if (newValue === "CUSTOM") {
      setIsCustom(true);
      onChange({
        frequency: "WEEKLY",
        interval: 1,
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
      until: undefined,
      ...getAdvancedProperties(value),
    });
  };

  const handleChange = (updates: Partial<IcsRecurrenceRule>) => {
    onChange({
      frequency: "WEEKLY",
      interval: 1,
      ...value,
      ...updates,
    });
  };

  const getSelectedDays = (): IcsWeekDay[] => {
    if (!value?.byDay) return [];
    return value.byDay.map((d) => (typeof d === "string" ? (d as IcsWeekDay) : d.day));
  };

  const isDaySelected = (day: IcsWeekDay): boolean => {
    return getSelectedDays().includes(day);
  };

  const toggleDay = (day: IcsWeekDay) => {
    const currentDays = getSelectedDays();
    const newDays = currentDays.includes(day)
      ? currentDays.filter((d) => d !== day)
      : [...currentDays, day];
    handleChange({ byDay: newDays.map((d) => ({ day: d })) });
  };

  const getMonthDay = (): number => {
    return value?.byMonthday?.[0] ?? 1;
  };

  const getMonth = (): string => {
    return String(value?.byMonth?.[0] ?? 1);
  };

  const handleMonthDayChange = (day: number) => {
    handleChange({ byMonthday: [day] });
  };

  const handleMonthChange = (month: number) => {
    handleChange({ byMonth: [month] });
  };

  const endType = getEndType(value);

  const monthDay = getMonthDay();
  const dateWarning =
    isCustom && value?.frequency === "YEARLY"
      ? getDateWarning(t, monthDay, parseInt(getMonth()))
      : null;

  const showAdvancedWarning = hasAdvancedProperties(value);

  return (
    <div className="recurrence-editor">
      <Select
        label={t("calendar.recurrence.label")}
        hideLabel
        value={getSimpleValue()}
        options={recurrenceOptions}
        onChange={(e) => handleSimpleChange(String(e.target.value ?? ""))}
        variant="classic"
        fullWidth
      />

      {showAdvancedWarning && (
        <Alert className="app__alert--small" type={VariantType.WARNING} icon={<Warning />}>
          {t("calendar.recurrence.advancedPropertiesWarning")}
        </Alert>
      )}

      {isCustom && (
        <div className="recurrence-editor__card">
          {summary && <div className="recurrence-editor__summary">{summary}</div>}

          <div className="recurrence-editor__interval">
            <span>{t("calendar.recurrence.everyLabel")}</span>
            <Input
              label=""
              type="number"
              variant="classic"
              min={1}
              max={999}
              value={value?.interval || 1}
              onChange={(e) => {
                const n = parseInt(e.target.value) || 1;
                handleChange({ interval: Math.min(Math.max(1, n), 999) });
              }}
            />
            <Select
              label=""
              variant="classic"
              value={value?.frequency || "WEEKLY"}
              options={frequencyOptions}
              onChange={(e) =>
                handleChange({
                  frequency: String(e.target.value ?? "") as RecurrenceFrequency,
                })
              }
            />
          </div>

          {value?.frequency === "WEEKLY" && (
            <div className="recurrence-editor__weekdays">
              {weekdays.map((day) => {
                const isSelected = isDaySelected(day.value);
                return (
                  <button
                    key={day.value}
                    type="button"
                    className={`recurrence-editor__weekday-button ${isSelected ? "recurrence-editor__weekday-button--selected" : ""}`}
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
          )}

          {value?.frequency === "MONTHLY" && (
            <div className="recurrence-editor__day-select">
              <span className="recurrence-editor__label">
                {t("calendar.recurrence.repeatOnDay")}
              </span>
              <div className="recurrence-editor__interval">
                <span>{t("calendar.recurrence.dayOfMonth")}</span>
                <Input
                  label=""
                  type="number"
                  min={1}
                  max={31}
                  variant="classic"
                  value={getMonthDay()}
                  onChange={(e) => {
                    const day = parseInt(e.target.value) || 1;
                    if (day >= 1 && day <= 31) {
                      handleMonthDayChange(day);
                    }
                  }}
                />
              </div>
            </div>
          )}

          {value?.frequency === "YEARLY" && (
            <div className="recurrence-editor__day-select">
              <span className="recurrence-editor__label">
                {t("calendar.recurrence.repeatOnDate")}
              </span>
              <div className="recurrence-editor__interval">
                <Select
                  label=""
                  value={getMonth()}
                  variant="classic"
                  options={monthOptions}
                  onChange={(e) => handleMonthChange(parseInt(String(e.target.value)) || 1)}
                />
                <Input
                  label=""
                  type="number"
                  variant="classic"
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
                <Alert className="app__alert--small" type={VariantType.WARNING} icon={<Warning />}>
                  {dateWarning}
                </Alert>
              )}
            </div>
          )}
        </div>
      )}

      {/* End-of-recurrence (never / after N / on date) is shown for every
          recurrence type */}
      {value && (
        <div className="recurrence-editor__card recurrence-editor__card--end-only">
          <div className="recurrence-editor__end">
            <span className="recurrence-editor__section-label">
              {t("calendar.recurrence.endsLabel")}
            </span>
            <div className="recurrence-editor__end-options">
              <button
                type="button"
                className={`recurrence-editor__end-btn ${endType === "never" ? "recurrence-editor__end-btn--active" : ""}`}
                onClick={() => handleChange({ count: undefined, until: undefined })}
              >
                {t("calendar.recurrence.never")}
              </button>
              <button
                type="button"
                className={`recurrence-editor__end-btn ${endType === "count" ? "recurrence-editor__end-btn--active" : ""}`}
                onClick={() => handleChange({ count: 10, until: undefined })}
              >
                {t("calendar.recurrence.after")}...
              </button>
              <button
                type="button"
                className={`recurrence-editor__end-btn ${endType === "date" ? "recurrence-editor__end-btn--active" : ""}`}
                onClick={() =>
                  handleChange({
                    until: { type: "DATE", date: new Date() },
                    count: undefined,
                  })
                }
              >
                {t("calendar.recurrence.on")}...
              </button>
            </div>

            {endType === "count" && (
              <div className="recurrence-editor__end-input">
                <Input
                  label=""
                  type="number"
                  variant="classic"
                  min={1}
                  max={9999}
                  value={value?.count ?? 10}
                  onChange={(e) => {
                    const n = parseInt(e.target.value) || 1;
                    handleChange({ count: Math.min(Math.max(1, n), 9999) });
                  }}
                />
                <span>{t("calendar.recurrence.occurrences")}</span>
              </div>
            )}

            {endType === "date" && (
              <div className="recurrence-editor__end-input">
                <Input
                  label=""
                  type="date"
                  variant="classic"
                  value={(() => {
                    const untilDate = value ? getResolvedUntilDate(value) : undefined;
                    return untilDate ? untilDate.toISOString().split("T")[0] : "";
                  })()}
                  onChange={(e) =>
                    handleChange({
                      until: {
                        type: "DATE",
                        date: new Date(e.target.value),
                      },
                    })
                  }
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
