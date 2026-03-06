import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Select } from "@gouvfr-lasuite/cunningham-react";
import { Badge } from "@gouvfr-lasuite/ui-kit";

import type { ResourcePrincipal } from "@/features/resources/api/useResourcePrincipals";
import { SectionRow } from "./SectionRow";

interface ResourcesSectionProps {
  resources: ResourcePrincipal[];
  onChange: (resources: ResourcePrincipal[]) => void;
  availableResources: ResourcePrincipal[];
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

type BadgeType =
  | "accent"
  | "neutral"
  | "danger"
  | "success"
  | "warning"
  | "info";

const getResourceIcon = (resourceType: string): string =>
  resourceType === "ROOM" ? "meeting_room" : "devices";

const getPartstatBadgeType = (
  email: string | undefined,
  eventAttendees?: { email: string; partstat?: string }[],
): BadgeType => {
  if (!email || !eventAttendees) return "neutral";
  const att = eventAttendees.find(
    (a) => a.email.toLowerCase() === email.toLowerCase(),
  );
  switch (att?.partstat) {
    case "ACCEPTED":
      return "success";
    case "DECLINED":
      return "danger";
    case "TENTATIVE":
      return "warning";
    default:
      return "neutral";
  }
};

export const ResourcesSection = ({
  resources: selectedResources,
  onChange,
  availableResources,
  alwaysOpen,
  isExpanded,
  onToggle,
}: ResourcesSectionProps) => {
  const { t } = useTranslation();

  const selectedIds = new Set(selectedResources.map((r) => r.id));
  const unselectedResources = availableResources.filter(
    (r) => !selectedIds.has(r.id),
  );

  const handleSelect = useCallback(
    (e: {
      target: { value: string | number | string[] | undefined };
    }) => {
      const id = e.target.value;
      if (!id || typeof id !== "string") return;
      const resource = availableResources.find((r) => r.id === id);
      if (resource) {
        onChange([...selectedResources, resource]);
      }
    },
    [availableResources, selectedResources, onChange],
  );

  const handleRemove = useCallback(
    (id: string) => {
      onChange(selectedResources.filter((r) => r.id !== id));
    },
    [selectedResources, onChange],
  );

  return (
    <SectionRow
      icon="meeting_room"
      label={t("calendar.event.sections.addResources")}
      isEmpty={selectedResources.length === 0}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
      iconAlign="flex-start"
    >
      <div className="attendees-input">
        {unselectedResources.length > 0 && (
          <div className="attendees-input__field">
            <Select
              label={t("calendar.resources.placeholder")}
              hideLabel
              options={unselectedResources.map((r) => ({
                value: r.id,
                label: `${r.name} (${t(`resources.types.${r.resourceType.toLowerCase()}`)})`,
              }))}
              value={undefined}
              onChange={handleSelect}
              clearable={false}
              variant="classic"
              fullWidth
              placeholder={t("calendar.resources.placeholder")}
            />
          </div>
        )}

        {selectedResources.length > 0 && (
          <div className="attendees-input__pills">
            {selectedResources.map((resource) => (
              <Badge
                key={resource.id}
                type={getPartstatBadgeType(resource.email)}
                className="attendees-input__pill"
              >
                <span className="material-icons">
                  {getResourceIcon(resource.resourceType)}
                </span>
                {resource.name}
                <button
                  type="button"
                  className="attendees-input__pill-remove"
                  onClick={() => handleRemove(resource.id)}
                  aria-label={t("calendar.resources.remove")}
                >
                  <span className="material-icons">close</span>
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>
    </SectionRow>
  );
};
