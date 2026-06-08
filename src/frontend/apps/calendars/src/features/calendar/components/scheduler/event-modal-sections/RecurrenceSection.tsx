import { useTranslation } from "react-i18next";
import { RecurrenceEditor } from "../RecurrenceEditor";
import { SectionRow } from "./SectionRow";
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";

import type { IcsRecurrenceRule } from "ts-ics";

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
      icon={<Icon name="repeat" type={IconType.OUTLINED} aria-hidden />}
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
