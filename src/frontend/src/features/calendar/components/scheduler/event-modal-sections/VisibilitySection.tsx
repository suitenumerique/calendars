import { useTranslation } from "react-i18next";
import { Select } from "@gouvfr-lasuite/cunningham-react";
import { Lock } from "@gouvfr-lasuite/ui-kit/icons";
import { SectionRow } from "./SectionRow";

import type { IcsClassType } from "ts-ics";

interface VisibilitySectionProps {
  visibility: IcsClassType;
  onChange: (value: IcsClassType) => void;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

// PUBLIC is the default. Order: least → most restrictive.
const OPTIONS: { value: IcsClassType; key: string }[] = [
  { value: "PUBLIC", key: "public" },
  { value: "CONFIDENTIAL", key: "confidential" },
  { value: "PRIVATE", key: "private" },
];

export const VisibilitySection = ({
  visibility,
  onChange,
  alwaysOpen,
  isExpanded,
  onToggle,
}: VisibilitySectionProps) => {
  const { t } = useTranslation();
  const current = OPTIONS.find((o) => o.value === visibility) ?? OPTIONS[0];

  return (
    <SectionRow
      icon={<Lock />}
      label={t("calendar.event.visibility.label")}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
      iconAlign="flex-start"
    >
      <div className="visibility-section">
        <Select
          label={t("calendar.event.visibility.label")}
          hideLabel
          value={visibility}
          onChange={(e) => onChange(e.target.value as IcsClassType)}
          options={OPTIONS.map((o) => ({
            value: o.value,
            label: t(`calendar.event.visibility.${o.key}`),
          }))}
          clearable={false}
          variant="classic"
          fullWidth
        />
        <p className="visibility-section__help">
          {t(`calendar.event.visibility.${current.key}Help`)}
        </p>
      </div>
    </SectionRow>
  );
};
