import { Select, Input } from "@gouvfr-lasuite/cunningham-react";
import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { IcsRecurrenceRule, IcsWeekDay } from "ts-ics";

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

interface RecurrenceEditorProps {
  value?: IcsRecurrenceRule;
  onChange: (rule: IcsRecurrenceRule | undefined) => void;
}

function getDateWarning(
  t: (key: string) => string,
  day: number,
  month?: number,
): string | null {
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

function getEndType(value?: IcsRecurrenceRule): EndType {
  if (value?.count) return "count";
  if (value?.until) return "date";
  return "never";
}

export function RecurrenceEditor({ value, onChange }: RecurrenceEditorProps) {
  const { t } = useTranslation();

  const [isCustom, setIsCustom] = useState(() => {
    if (!value) return false;
    return !!(
      value.interval !== 1 ||
      value.byDay?.length ||
      value.byMonthday?.length ||
      value.byMonth?.length ||
      value.count ||
      value.until
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
        label: t(`calendar.recurrence.months.${month.key}`),
      })),
    [t],
  );

  const summary = useMemo((): string => {
    if (!isCustom || !value) return "";

    const interval = value.interval || 1;
    const freq = value.frequency;
    const freqLabel = t(`calendar.recurrence.${freq === "DAILY" ? "days" : freq === "WEEKLY" ? "weeks" : freq === "MONTHLY" ? "months" : "years"}`);

    let result = `${t("calendar.recurrence.everyLabel")} ${interval > 1 ? `${interval} ` : ""}${freqLabel}`;

    if (freq === "WEEKLY" && value.byDay?.length) {
      const dayLabels = value.byDay.map((d) => {
        const dayKey = typeof d === "string" ? d : d.day;
        return t(
          `calendar.recurrence.weekdays.${dayKey.toLowerCase()}`,
        );
      });
      result += ` · ${dayLabels.join(", ")}`;
    }

    if (value.until) {
      const dateStr =
        value.until.date instanceof Date
          ? value.until.date.toISOString().split("T")[0]
          : "";
      result += ` · ${t("calendar.recurrence.on")} ${dateStr}`;
    } else if (value.count) {
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
    return value.byDay.map((d) =>
      typeof d === "string" ? (d as IcsWeekDay) : d.day,
    );
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
  const selectedMonth =
    value?.frequency === "YEARLY" ? parseInt(getMonth()) : undefined;
  const dateWarning =
    isCustom &&
    (value?.frequency === "MONTHLY" || value?.frequency === "YEARLY")
      ? getDateWarning(t, monthDay, selectedMonth)
      : null;


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

      {isCustom && (
        <div className="recurrence-editor__card">
          {summary && (
            <div className="recurrence-editor__summary">{summary}</div>
          )}

          <div className="recurrence-editor__interval">
            <span>{t("calendar.recurrence.everyLabel")}</span>
            <Input
              label=""
              type="number"
              variant="classic"
              min={1}
              value={value?.interval || 1}
              onChange={(e) =>
                handleChange({ interval: parseInt(e.target.value) || 1 })
              }
            />
            <Select
              label=""
              variant="classic"
              value={value?.frequency || "WEEKLY"}
              options={frequencyOptions}
              onChange={(e) =>
                handleChange({
                  frequency: String(
                    e.target.value ?? "",
                  ) as RecurrenceFrequency,
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
              {dateWarning && (
                <div className="recurrence-editor__warning">
                  {dateWarning}
                </div>
              )}
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
                  onChange={(e) =>
                    handleMonthChange(parseInt(String(e.target.value)) || 1)
                  }
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
                <div className="recurrence-editor__warning">
                  {dateWarning}
                </div>
              )}
            </div>
          )}

          <div className="recurrence-editor__end">
            <span className="recurrence-editor__section-label">
              {t("calendar.recurrence.endsLabel")}
            </span>
            <div className="recurrence-editor__end-options">
              <button
                type="button"
                className={`recurrence-editor__end-btn ${endType === "never" ? "recurrence-editor__end-btn--active" : ""}`}
                onClick={() =>
                  handleChange({ count: undefined, until: undefined })
                }
              >
                {t("calendar.recurrence.never")}
              </button>
              <button
                type="button"
                className={`recurrence-editor__end-btn ${endType === "count" ? "recurrence-editor__end-btn--active" : ""}`}
                onClick={() =>
                  handleChange({ count: 10, until: undefined })
                }
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
                  value={value?.count ?? 10}
                  onChange={(e) =>
                    handleChange({ count: parseInt(e.target.value) || 1 })
                  }
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
                  value={
                    value?.until?.date instanceof Date
                      ? value.until.date.toISOString().split("T")[0]
                      : ""
                  }
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
