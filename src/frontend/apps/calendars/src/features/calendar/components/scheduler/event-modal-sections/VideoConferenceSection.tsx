import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { SectionRow } from "./SectionRow";

interface VideoConferenceSectionProps {
  url: string;
  onChange: (url: string) => void;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

export const VideoConferenceSection = ({
  url,
  onChange,
  alwaysOpen,
  isExpanded,
  onToggle,
}: VideoConferenceSectionProps) => {
  const { t } = useTranslation();
  const [isCreating, setIsCreating] = useState(false);

  const handleCreateVisio = () => {
    // Inert for now - will integrate with La Suite API in the future
    setIsCreating(true);
    setTimeout(() => {
      setIsCreating(false);
    }, 500);
  };

  const handleRemove = () => {
    onChange("");
  };

  return (
    <SectionRow
      icon="videocam"
      label={t("calendar.event.sections.addVideoConference")}
      isEmpty={!url}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      <Button
        size="small"
        color="neutral"
        variant="tertiary"
        onClick={handleCreateVisio}
        disabled={isCreating}
      >
        {t("calendar.event.sections.createVisio")}
      </Button>
    </SectionRow>
  );
};
