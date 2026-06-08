import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { SectionRow } from "./SectionRow";
import { generateVisioRoomId } from "./generateVisioRoomId";
import { sanitizeIcsUrl } from "../../../services/dav/EventCalendarAdapter";
import { XMark, Meet } from "@gouvfr-lasuite/ui-kit/icons";

interface VideoConferenceSectionProps {
  url: string;
  onChange: (url: string) => void;
  baseUrl: string;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

export const VideoConferenceSection = ({
  url,
  onChange,
  baseUrl,
  alwaysOpen,
  isExpanded,
  onToggle,
}: VideoConferenceSectionProps) => {
  const { t } = useTranslation();

  // SECURITY: even though EventCalendarAdapter sanitizes the ICS URL
  // property at the data boundary, also sanitize here at the sink so
  // any future code path that constructs ``url`` from a different
  // source still gets filtered before it lands in <a href={url}>.
  // The cost is one extra parse on render; the benefit is a hard
  // guarantee that this <a> can never carry javascript:/data:/file:.
  const safeUrl = sanitizeIcsUrl(url);

  const handleCreateVisio = () => {
    if (!baseUrl) return;
    const roomId = generateVisioRoomId();
    onChange(`${baseUrl.replace(/\/$/, "")}/${roomId}`);
  };

  const handleRemove = () => {
    onChange("");
  };

  return (
    <SectionRow
      icon={<Meet />}
      label={t("calendar.event.sections.addVideoConference")}
      isEmpty={!url}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      {safeUrl ? (
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <a
            href={safeUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{ wordBreak: "break-all" }}
          >
            {safeUrl}
          </a>
          <Button
            size="small"
            color="neutral"
            variant="tertiary"
            icon={<XMark />}
            onClick={handleRemove}
            aria-label={t("calendar.event.sections.removeVisio")}
          />
        </div>
      ) : (
        <Button size="small" color="neutral" variant="tertiary" onClick={handleCreateVisio}>
          {t("calendar.event.sections.createVisio")}
        </Button>
      )}
    </SectionRow>
  );
};
