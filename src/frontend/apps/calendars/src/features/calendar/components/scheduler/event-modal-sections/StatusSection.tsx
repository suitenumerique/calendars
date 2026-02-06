import { useTranslation } from "react-i18next";
import { Select } from "@gouvfr-lasuite/cunningham-react";
import type {
  IcsClassType,
  IcsEventStatusType,
  IcsTimeTransparentType,
} from "ts-ics";
import { SectionRow } from "./SectionRow";

interface StatusSectionProps {
  status: IcsEventStatusType;
  visibility: IcsClassType;
  availability: IcsTimeTransparentType;
  onStatusChange: (value: IcsEventStatusType) => void;
  onVisibilityChange: (value: IcsClassType) => void;
  onAvailabilityChange: (value: IcsTimeTransparentType) => void;
  isExpanded?: boolean;
  onToggle?: () => void;
}

export const StatusSection = ({
  status,
  visibility,
  availability,
  onStatusChange,
  onVisibilityChange,
  onAvailabilityChange,
  isExpanded,
  onToggle,
}: StatusSectionProps) => {
  const { t } = useTranslation();

  const statusLabel = t(`calendar.event.status.${status.toLowerCase()}`);
  const visibilityLabel = t(
    `calendar.event.visibility.${visibility.toLowerCase()}`,
  );
  const availabilityLabel =
    availability === "OPAQUE"
      ? t("calendar.event.availability.busy")
      : t("calendar.event.availability.free");

  const summary = `${statusLabel} · ${visibilityLabel} · ${availabilityLabel}`;

  return (
    <SectionRow
      icon="info_outline"
      label={t("calendar.event.sections.moreOptions")}
      summary={summary}
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      <div className="status-section">
        <Select
          label={t("calendar.event.status.label")}
          value={status}
          onChange={(e) =>
            onStatusChange(e.target.value as IcsEventStatusType)
          }
          options={[
            {
              value: "CONFIRMED",
              label: t("calendar.event.status.confirmed"),
            },
            {
              value: "TENTATIVE",
              label: t("calendar.event.status.tentative"),
            },
            {
              value: "CANCELLED",
              label: t("calendar.event.status.cancelled"),
            },
          ]}
          fullWidth
        />
        <Select
          label={t("calendar.event.visibility.label")}
          value={visibility}
          onChange={(e) => onVisibilityChange(e.target.value as IcsClassType)}
          options={[
            { value: "PUBLIC", label: t("calendar.event.visibility.public") },
            {
              value: "PRIVATE",
              label: t("calendar.event.visibility.private"),
            },
            {
              value: "CONFIDENTIAL",
              label: t("calendar.event.visibility.confidential"),
            },
          ]}
          fullWidth
        />
        <Select
          label={t("calendar.event.availability.label")}
          value={availability}
          onChange={(e) =>
            onAvailabilityChange(e.target.value as IcsTimeTransparentType)
          }
          options={[
            {
              value: "OPAQUE",
              label: t("calendar.event.availability.busy"),
            },
            {
              value: "TRANSPARENT",
              label: t("calendar.event.availability.free"),
            },
          ]}
          fullWidth
        />
      </div>
    </SectionRow>
  );
};
