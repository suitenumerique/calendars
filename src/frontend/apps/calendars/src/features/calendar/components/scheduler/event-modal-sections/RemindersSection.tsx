import { useTranslation } from "react-i18next";
import { Button, Select } from "@gouvfr-lasuite/cunningham-react";
import type { IcsAlarm } from "ts-ics";
import { SectionRow } from "./SectionRow";

interface RemindersSectionProps {
  alarms: IcsAlarm[];
  onChange: (alarms: IcsAlarm[]) => void;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

const REMINDER_PRESETS = [
  { minutes: 5, key: "5min" },
  { minutes: 15, key: "15min" },
  { minutes: 30, key: "30min" },
  { minutes: 60, key: "1hour" },
  { minutes: 1440, key: "1day" },
  { minutes: 10080, key: "1week" },
];

const alarmToMinutes = (alarm: IcsAlarm): number => {
  const trigger = alarm.trigger;
  if (trigger.type !== "relative") return 15;
  const d = trigger.value;
  return (
    (d.weeks || 0) * 10080 +
    (d.days || 0) * 1440 +
    (d.hours || 0) * 60 +
    (d.minutes || 0)
  );
};

const minutesToAlarm = (minutes: number): IcsAlarm => ({
  action: "DISPLAY",
  trigger: {
    type: "relative",
    value: {
      before: true,
      ...(minutes >= 10080 && minutes % 10080 === 0
        ? { weeks: minutes / 10080 }
        : minutes >= 1440 && minutes % 1440 === 0
          ? { days: minutes / 1440 }
          : minutes >= 60 && minutes % 60 === 0
            ? { hours: minutes / 60 }
            : { minutes }),
    },
  },
});

export const RemindersSection = ({
  alarms,
  onChange,
  alwaysOpen,
  isExpanded,
  onToggle,
}: RemindersSectionProps) => {
  const { t } = useTranslation();

  const handleAdd = () => {
    onChange([...alarms, minutesToAlarm(15)]);
  };

  const handleRemove = (index: number) => {
    onChange(alarms.filter((_, i) => i !== index));
  };

  const handleChange = (index: number, minutes: number) => {
    const updated = [...alarms];
    updated[index] = minutesToAlarm(minutes);
    onChange(updated);
  };

  const presetOptions = REMINDER_PRESETS.map((p) => ({
    value: String(p.minutes),
    label: t(`calendar.event.reminders.${p.key}`),
  }));

  return (
    <SectionRow
      icon="notifications"
      label={t("calendar.event.sections.addReminder")}
      isEmpty={alarms.length === 0}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      <div className="reminders-section">
        {alarms.map((alarm, index) => (
          <div key={index} className="reminders-section__item">
            <Select
              label=""
              value={String(alarmToMinutes(alarm))}
              onChange={(e) => handleChange(index, Number(e.target.value))}
              options={presetOptions}
              fullWidth
            />
            <button
              type="button"
              className="reminders-section__remove"
              onClick={() => handleRemove(index)}
              aria-label={t("common.cancel")}
            >
              <span className="material-icons">close</span>
            </button>
          </div>
        ))}
        <Button size="small" color="neutral" onClick={handleAdd}>
          <span className="material-icons" style={{ fontSize: 16 }}>
            add
          </span>
          {t("calendar.event.sections.addReminder")}
        </Button>
      </div>
    </SectionRow>
  );
};
