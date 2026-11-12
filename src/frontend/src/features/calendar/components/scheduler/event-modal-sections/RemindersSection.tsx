import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Button, Select } from "@gouvfr-lasuite/ui-components";
import { SectionRow } from "./SectionRow";
import { Bell, Plus, XMark } from "@gouvfr-lasuite/ui-components/icons";
import {
  createDefaultAlarm,
  getPresetMinutes,
  REMINDER_PRESETS,
  withPresetTrigger,
} from "./reminderPresets";

import type { IcsAlarm, IcsDuration } from "ts-ics";

interface RemindersSectionProps {
  alarms: IcsAlarm[];
  onChange: (alarms: IcsAlarm[]) => void;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

// The select value of an alarm that matches no preset.
const CUSTOM_VALUE = "custom";

const DURATION_UNITS = [
  ["weeks", "week"],
  ["days", "day"],
  ["hours", "hour"],
  ["minutes", "minute"],
  ["seconds", "second"],
] as const;

const formatDuration = (duration: IcsDuration, locale: string): string =>
  DURATION_UNITS.filter(([key]) => duration[key])
    .map(([key, unit]) =>
      new Intl.NumberFormat(locale, { style: "unit", unit, unitDisplay: "long" }).format(
        duration[key] ?? 0,
      ),
    )
    .join(" ");

/** The label of an alarm that matches no preset. */
const describeCustomAlarm = (alarm: IcsAlarm, t: TFunction, locale: string): string => {
  const { trigger } = alarm;
  if (trigger.type === "absolute") {
    return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
      trigger.value.date,
    );
  }

  const anchor = trigger.options?.related === "END" ? "End" : "Start";
  const duration = formatDuration(trigger.value, locale);
  if (!duration) return t(`calendar.event.reminders.at${anchor}`);

  const direction = trigger.value.before ? "before" : "after";
  return t(`calendar.event.reminders.${direction}${anchor}`, { duration });
};

export const RemindersSection = ({
  alarms,
  onChange,
  alwaysOpen,
  isExpanded,
  onToggle,
}: RemindersSectionProps) => {
  const { t, i18n } = useTranslation();

  const handleAdd = () => {
    onChange([...alarms, createDefaultAlarm()]);
  };

  const handleRemove = (index: number) => {
    onChange(alarms.filter((_, i) => i !== index));
  };

  const handleChange = (index: number, value: string) => {
    // The custom option stands for the alarm as it is.
    if (value === CUSTOM_VALUE) return;
    const updated = [...alarms];
    updated[index] = withPresetTrigger(alarms[index], Number(value));
    onChange(updated);
  };

  const presetOptions = REMINDER_PRESETS.map((p) => ({
    value: String(p.minutes),
    label: t(`calendar.event.reminders.${p.key}`),
  }));

  return (
    <SectionRow
      icon={<Bell />}
      label={t("calendar.event.sections.addReminder")}
      isEmpty={alarms.length === 0}
      alwaysOpen={alwaysOpen}
      iconAlign="flex-start"
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      <div className="reminders-section">
        {alarms.map((alarm, index) => {
          const presetMinutes = getPresetMinutes(alarm);
          const value = presetMinutes === null ? CUSTOM_VALUE : String(presetMinutes);
          const options =
            presetMinutes === null
              ? [
                  { value: CUSTOM_VALUE, label: describeCustomAlarm(alarm, t, i18n.language) },
                  ...presetOptions,
                ]
              : presetOptions;

          return (
            <div key={`${value}-${index}`} className="reminders-section__item">
              <Select
                label={t("calendar.event.reminders.label")}
                hideLabel
                value={value}
                onChange={(e) => handleChange(index, String(e.target.value))}
                options={options}
                clearable={false}
                variant="classic"
                fullWidth
              />
              <button
                type="button"
                className="reminders-section__remove"
                onClick={() => handleRemove(index)}
                aria-label={t("calendar.event.reminders.remove")}
              >
                <XMark />
              </button>
            </div>
          );
        })}
        <Button
          className="reminders-section__add"
          size="small"
          color="neutral"
          variant="tertiary"
          icon={<Plus />}
          onClick={handleAdd}
        >
          {t("calendar.event.sections.addReminder")}
        </Button>
      </div>
    </SectionRow>
  );
};
