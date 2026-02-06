import { useTranslation } from "react-i18next";
import { TextArea } from "@gouvfr-lasuite/cunningham-react";
import { SectionRow } from "./SectionRow";

interface DescriptionSectionProps {
  description: string;
  onChange: (value: string) => void;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

export const DescriptionSection = ({
  description,
  onChange,
  alwaysOpen,
  isExpanded,
  onToggle,
}: DescriptionSectionProps) => {
  const { t } = useTranslation();

  return (
    <SectionRow
      icon="notes"
      label={t("calendar.event.sections.addDescription")}
      isEmpty={!description}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
      iconAlign="flex-start"
    >
      <TextArea
        label={t("calendar.event.description")}
        placeholder={t("calendar.event.descriptionPlaceholder")}
        value={description}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        fullWidth
        variant="classic"
        hideLabel
      />
    </SectionRow>
  );
};
