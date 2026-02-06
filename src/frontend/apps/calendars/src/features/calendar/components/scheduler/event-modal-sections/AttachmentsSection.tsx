import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import type { AttachmentMeta } from "../types";
import { SectionRow } from "./SectionRow";

interface AttachmentsSectionProps {
  attachments: AttachmentMeta[];
  onChange: (attachments: AttachmentMeta[]) => void;
  isExpanded?: boolean;
  onToggle?: () => void;
}

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export const AttachmentsSection = ({
  attachments,
  onChange,
  isExpanded,
  onToggle,
}: AttachmentsSectionProps) => {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const summary =
    attachments.length > 0
      ? `${attachments.length} ${t("calendar.event.sections.attachment", { count: attachments.length })}`
      : undefined;

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    const newAttachments: AttachmentMeta[] = Array.from(files).map((file) => ({
      id: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      type: file.type,
    }));

    onChange([...attachments, ...newAttachments]);

    // Reset input
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleRemove = (id: string) => {
    onChange(attachments.filter((a) => a.id !== id));
  };

  return (
    <SectionRow
      icon="attach_file"
      label={t("calendar.event.sections.addAttachment")}
      summary={summary}
      isEmpty={attachments.length === 0}
      isExpanded={isExpanded}
      onToggle={onToggle}
    >
      <div className="attachments-section">
        {attachments.map((attachment) => (
          <div key={attachment.id} className="attachments-section__item">
            <span className="material-icons" style={{ fontSize: 18 }}>
              description
            </span>
            <div className="attachments-section__info">
              <span className="attachments-section__name">
                {attachment.name}
              </span>
              <span className="attachments-section__size">
                {formatFileSize(attachment.size)}
              </span>
            </div>
            <button
              type="button"
              className="attachments-section__remove"
              onClick={() => handleRemove(attachment.id)}
              aria-label={t("common.cancel")}
            >
              <span className="material-icons">close</span>
            </button>
          </div>
        ))}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileSelect}
          style={{ display: "none" }}
        />
        <Button
          size="small"
          color="neutral"
          onClick={() => fileInputRef.current?.click()}
        >
          <span className="material-icons" style={{ fontSize: 16 }}>
            add
          </span>
          {t("calendar.event.sections.addAttachment")}
        </Button>
      </div>
    </SectionRow>
  );
};
