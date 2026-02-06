import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { SectionRow } from "./SectionRow";
import { generateVisioRoomId } from "./generateVisioRoomId";

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

  const handleCreateVisio = () => {
    const baseUrl = process.env.NEXT_PUBLIC_VISIO_BASE_URL;
    if (!baseUrl) return;
    const roomId = generateVisioRoomId();
    onChange(`${baseUrl}/${roomId}`);
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
      {url ? (
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ wordBreak: "break-all" }}
          >
            {url}
          </a>
          <Button
            size="small"
            color="neutral"
            variant="tertiary"
            icon={<span className="material-icons">close</span>}
            onClick={handleRemove}
            aria-label={t("calendar.event.sections.removeVisio")}
          />
        </div>
      ) : (
        <Button
          size="small"
          color="neutral"
          variant="tertiary"
          onClick={handleCreateVisio}
        >
          {t("calendar.event.sections.createVisio")}
        </Button>
      )}
    </SectionRow>
  );
};
