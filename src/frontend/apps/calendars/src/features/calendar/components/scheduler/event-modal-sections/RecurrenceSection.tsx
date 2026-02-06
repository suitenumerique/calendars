import { useTranslation } from "react-i18next";
import type { IcsRecurrenceRule } from "ts-ics";
import { RecurrenceEditor } from "../RecurrenceEditor";
import { SectionRow } from "./SectionRow";

interface RecurrenceSectionProps {
  recurrence: IcsRecurrenceRule | undefined;
  onChange: (value: IcsRecurrenceRule | undefined) => void;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

export const RecurrenceSection = ({
  recurrence,
  onChange,
  alwaysOpen,
  isExpanded,
  onToggle,
}: RecurrenceSectionProps) => {
  const { t } = useTranslation();

  return (
    <SectionRow
      icon="repeat"
      label={t("calendar.event.sections.addRecurrence")}
      isEmpty={!recurrence}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
      iconAlign="flex-start"
    >
      <RecurrenceEditor value={recurrence} onChange={onChange} />
    </SectionRow>
  );
};
