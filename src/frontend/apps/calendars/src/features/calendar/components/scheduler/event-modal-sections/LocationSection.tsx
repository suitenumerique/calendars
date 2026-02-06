import { useTranslation } from "react-i18next";
import { Input } from "@gouvfr-lasuite/cunningham-react";
import { SectionRow } from "./SectionRow";

interface LocationSectionProps {
  location: string;
  onChange: (value: string) => void;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

export const LocationSection = ({
  location,
  onChange,
  alwaysOpen,
  isExpanded,
  onToggle,
}: LocationSectionProps) => {
  const { t } = useTranslation();

  return (
    <SectionRow
      icon="place"
      label={t("calendar.event.sections.addLocation")}
      isEmpty={!location}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      <Input
        label={t("calendar.event.location")}
        hideLabel
        value={location}
        placeholder={t("calendar.event.locationPlaceholder")}
        onChange={(e) => onChange(e.target.value)}
        variant="classic"
        fullWidth
      />
    </SectionRow>
  );
};
