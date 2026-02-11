/**
 * CalendarModal component.
 * Handles creation and editing of calendars.
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
}: CalendarModalProps) => {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [color, setColor] = useState(DEFAULT_COLORS[0]);
  const [description, setDescription] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const handleClose = () => {
    setName("");
    setColor(DEFAULT_COLORS[0]);
    setDescription("");
    setError(null);
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
      </div>
    </Modal>
  );
};
