/**
 * CalendarModal component.
 * Handles creation and editing of calendars, including sharing.
 */

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Input,
  Modal,
  ModalSize,
  TextArea,
} from "@gouvfr-lasuite/cunningham-react";

import { DEFAULT_COLORS } from "./constants";
import type { CalendarModalProps } from "./types";

export const CalendarModal = ({
  isOpen,
  mode,
  calendar,
  onClose,
  onSave,
  onShare,
}: CalendarModalProps) => {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [color, setColor] = useState(DEFAULT_COLORS[0]);
  const [description, setDescription] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Share state
  const [shareEmail, setShareEmail] = useState("");
  const [isSharing, setIsSharing] = useState(false);
  const [shareSuccess, setShareSuccess] = useState<string | null>(null);
  const [shareError, setShareError] = useState<string | null>(null);

  // Reset form when modal opens or calendar changes
  useEffect(() => {
    if (isOpen) {
      if (mode === "edit" && calendar) {
        setName(calendar.displayName || "");
        setColor(calendar.color || DEFAULT_COLORS[0]);
        setDescription(calendar.description || "");
      } else {
        setName("");
        setColor(DEFAULT_COLORS[0]);
        setDescription("");
      }
      setError(null);
      setShareEmail("");
      setShareSuccess(null);
      setShareError(null);
    }
  }, [isOpen, mode, calendar]);

  const handleSave = async () => {
    if (!name.trim()) {
      setError(t('calendar.createCalendar.nameRequired'));
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      await onSave(name.trim(), color, description.trim() || undefined);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('api.error.unexpected'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleShare = async () => {
    if (!shareEmail.trim() || !onShare) return;

    // Basic email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(shareEmail.trim())) {
      setShareError(t('calendar.shareCalendar.invalidEmail'));
      return;
    }

    setIsSharing(true);
    setShareError(null);
    setShareSuccess(null);

    try {
      const result = await onShare(shareEmail.trim());
      if (result.success) {
        setShareSuccess(
          t('calendar.shareCalendar.success', { email: shareEmail.trim() })
        );
        setShareEmail("");
      } else {
        setShareError(result.error || t('calendar.shareCalendar.error'));
      }
    } catch (err) {
      setShareError(
        err instanceof Error ? err.message : t('calendar.shareCalendar.error')
      );
    } finally {
      setIsSharing(false);
    }
  };

  const handleClose = () => {
    setName("");
    setColor(DEFAULT_COLORS[0]);
    setDescription("");
    setError(null);
    setShareEmail("");
    setShareSuccess(null);
    setShareError(null);
    onClose();
  };

  const title =
    mode === "create"
      ? t('calendar.createCalendar.title')
      : t('calendar.editCalendar.title');

  const saveLabel =
    mode === "create"
      ? t('calendar.createCalendar.create')
      : t('calendar.editCalendar.save');

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size={ModalSize.MEDIUM}
      title={title}
      rightActions={
        <>
          <Button color="neutral" onClick={handleClose} disabled={isLoading}>
            {t('calendar.event.cancel')}
          </Button>
          <Button
            color="brand"
            onClick={handleSave}
            disabled={isLoading || !name.trim()}
          >
            {isLoading ? "..." : saveLabel}
          </Button>
        </>
      }
    >
      <div className="calendar-modal__content">
        {error && <div className="calendar-modal__error">{error}</div>}

        <Input
          label={t('calendar.createCalendar.name')}
          value={name}
          onChange={(e) => setName(e.target.value)}
          fullWidth
        />

        <div className="calendar-modal__field">
          <label className="calendar-modal__label">
            {t('calendar.createCalendar.color')}
          </label>
          <div className="calendar-modal__colors">
            {DEFAULT_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                className={`calendar-modal__color-btn ${
                  color === c ? 'calendar-modal__color-btn--selected' : ''
                }`}
                style={{ backgroundColor: c }}
                onClick={() => setColor(c)}
                aria-label={c}
              />
            ))}
          </div>
        </div>

        <TextArea
          label={t('calendar.createCalendar.description')}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          fullWidth
        />

        {/* Share section - only visible in edit mode */}
        {mode === "edit" && onShare && (
          <div className="calendar-modal__share-section">
            <div className="calendar-modal__share-divider" />
            <label className="calendar-modal__label">
              <span className="material-icons">person_add</span>
              {t('calendar.shareCalendar.title')}
            </label>

            {shareSuccess && (
              <div className="calendar-modal__success">{shareSuccess}</div>
            )}
            {shareError && (
              <div className="calendar-modal__error">{shareError}</div>
            )}

            <div className="calendar-modal__share-input-row">
              <Input
                label=""
                value={shareEmail}
                onChange={(e) => setShareEmail(e.target.value)}
                placeholder={t('calendar.shareCalendar.emailPlaceholder')}
                fullWidth
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleShare();
                  }
                }}
              />
              <Button
                color="brand"
                onClick={handleShare}
                disabled={isSharing || !shareEmail.trim()}
              >
                {isSharing ? "..." : t('calendar.shareCalendar.share')}
              </Button>
            </div>
            <p className="calendar-modal__share-hint">
              {t('calendar.shareCalendar.hint')}
            </p>
          </div>
        )}
      </div>
    </Modal>
  );
};
