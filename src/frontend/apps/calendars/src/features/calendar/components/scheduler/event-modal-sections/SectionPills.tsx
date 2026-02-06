import { SectionPill } from "./SectionPill";
import type { EventFormSectionId } from "../types";

interface PillConfig {
  id: EventFormSectionId;
  icon: string;
  label: string;
}

interface SectionPillsProps {
  pills: PillConfig[];
  isSectionExpanded: (id: EventFormSectionId) => boolean;
  onToggle: (id: EventFormSectionId) => void;
}

export const SectionPills = ({
  pills,
  isSectionExpanded,
  onToggle,
}: SectionPillsProps) => {
  return (
    <div className="section-pills">
      {pills.map((pill) => (
        <SectionPill
          key={pill.id}
          icon={pill.icon}
          label={pill.label}
          isActive={isSectionExpanded(pill.id)}
          onClick={() => onToggle(pill.id)}
        />
      ))}
    </div>
  );
};
