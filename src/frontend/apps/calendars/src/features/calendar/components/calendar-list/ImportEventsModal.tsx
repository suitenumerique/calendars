/**
 * ImportEventsModal component.
 * Allows users to import events from an ICS file into a calendar.
 */

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";

import { useImportEvents } from "../../hooks/useCalendars";
import type { ImportEventsResult } from "../../api";

interface ImportEventsModalProps {
  isOpen: boolean;
  calendarId: string;
  calendarName: string;
  onClose: () => void;
  onImportSuccess?: () => void;
}

export const ImportEventsModal = ({
  isOpen,
  calendarId,
  calendarName,
  onClose,
  onImportSuccess,
}: ImportEventsModalProps) => {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportEventsResult | null>(null);
  const importMutation = useImportEvents();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setResult(null);
  };

  const handleImport = async () => {
    if (!selectedFile) return;

    const importResult = await importMutation.mutateAsync({
      calendarId,
      file: selectedFile,
    });
    setResult(importResult);
    if (importResult.imported_count > 0) {
      onImportSuccess?.();
    }
  };

  const handleClose = () => {
    setSelectedFile(null);
    setResult(null);
    importMutation.reset();
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    onClose();
  };

  const hasResult = result !== null;
  const hasErrors = result && result.errors && result.errors.length > 0;

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size={ModalSize.MEDIUM}
      title={t("calendar.importEvents.title")}
      rightActions={
        hasResult ? (
          <Button color="brand" onClick={handleClose}>
            {t("calendar.subscription.close")}
          </Button>
        ) : (
          <>
            <Button color="neutral" onClick={handleClose}>
              {t("calendar.event.cancel")}
            </Button>
            <Button
              color="brand"
              onClick={handleImport}
              disabled={!selectedFile || importMutation.isPending}
            >
              {importMutation.isPending
                ? <Spinner size="sm" />
                : t("calendar.importEvents.import")}
            </Button>
          </>
        )
      }
    >
      <div className="import-events-modal">
        <p className="import-events-modal__description">
          {t("calendar.importEvents.description", { name: calendarName })}
        </p>

        {!hasResult && (
          <div className="import-events-modal__file-section">
            <input
              ref={fileInputRef}
              type="file"
              accept=".ics,.ical,.ifb,.icalendar,text/calendar"
              onChange={handleFileChange}
              style={{ display: "none" }}
            />
            <Button
              color="neutral"
              onClick={() => fileInputRef.current?.click()}
              icon={
                <span className="material-icons">upload_file</span>
              }
            >
              {t("calendar.importEvents.selectFile")}
            </Button>
            {selectedFile && (
              <span className="import-events-modal__filename">
                {selectedFile.name}
              </span>
            )}
          </div>
        )}

        {importMutation.isError && !hasResult && (
          <div className="import-events-modal__error">
            {t("calendar.importEvents.error")}
          </div>
        )}

        {hasResult && (
          <div className="import-events-modal__result">
            <p className="import-events-modal__result-header">
              {t("calendar.importEvents.resultHeader")}
            </p>
            <ul className="import-events-modal__stats">
              {result.imported_count > 0 && (
                <li className="import-events-modal__stat import-events-modal__stat--success">
                  <span className="material-icons">check_circle</span>
                  <span><strong>{result.imported_count}</strong> {t("calendar.importEvents.imported")}</span>
                </li>
              )}
              {result.duplicate_count > 0 && (
                <li className="import-events-modal__stat import-events-modal__stat--neutral">
                  <span className="material-icons">content_copy</span>
                  <span><strong>{result.duplicate_count}</strong> {t("calendar.importEvents.duplicates")}</span>
                </li>
              )}
              {result.skipped_count > 0 && (
                <li className="import-events-modal__stat import-events-modal__stat--warning">
                  <span className="material-icons">warning_amber</span>
                  <span><strong>{result.skipped_count}</strong> {t("calendar.importEvents.skipped")}</span>
                </li>
              )}
            </ul>
            {hasErrors && (
              <details className="import-events-modal__errors">
                <summary>{t("calendar.importEvents.errorDetails")}</summary>
                <ul>
                  {result.errors!.map((error, index) => (
                    <li key={index}>{error}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};
