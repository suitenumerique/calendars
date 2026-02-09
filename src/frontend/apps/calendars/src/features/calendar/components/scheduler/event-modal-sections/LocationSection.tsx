import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input } from "@gouvfr-lasuite/cunningham-react";
import { SectionRow } from "./SectionRow";
import { extractUrl } from "../utils/eventDisplayRules";

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
  const detectedUrl = useMemo(() => extractUrl(location), [location]);

  return (
    <SectionRow
      icon="place"
      label={t("calendar.event.sections.addLocation")}
      isEmpty={!location}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
        <Input
          label={t("calendar.event.location")}
          hideLabel
          value={location}
          placeholder={t("calendar.event.locationPlaceholder")}
          onChange={(e) => onChange(e.target.value)}
          variant="classic"
          fullWidth
        />
        {detectedUrl && (
          <Button
            size="small"
            color="neutral"
            variant="tertiary"
            icon={<span className="material-icons">open_in_new</span>}
            href={detectedUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("calendar.event.openLocation", "Open")}
          </Button>
        )}
      </div>
    </SectionRow>
  );
};
