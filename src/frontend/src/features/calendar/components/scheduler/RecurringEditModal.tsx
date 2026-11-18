/**
 * RecurringEditModal component.
 * Displays options for editing recurring events:
 * this occurrence, this and future, or all occurrences.
 */

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/ui-components";

import type { RecurringEditModalProps, RecurringEditOption } from "./types";

export const RecurringEditModal = ({
  isOpen,
  onConfirm,
  onCancel,
  title,
  prompt,
  confirmLabel,
  disableFuture = false,
  disableThis = false,
}: RecurringEditModalProps) => {
  const { t } = useTranslation();
  const initialOption: RecurringEditOption = disableThis ? "all" : "this";
  const [selectedOption, setSelectedOption] = useState<RecurringEditOption>(initialOption);

  useEffect(() => {
    if (isOpen) {
      setSelectedOption(initialOption);
    }
  }, [isOpen, initialOption]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      title={title ?? t("calendar.event.editRecurringTitle")}
      size={ModalSize.SMALL}
      rightActions={
        <>
          <Button color="neutral" onClick={onCancel}>
            {t("calendar.event.cancel")}
          </Button>
          <Button color="brand" onClick={() => onConfirm(selectedOption)}>
            {confirmLabel ?? t("calendar.event.save")}
          </Button>
        </>
      }
    >
      <div className="delete-modal__content">
        <p className="delete-modal__message">{prompt ?? t("calendar.event.editRecurringPrompt")}</p>
        <div className="delete-modal__options">
          {!disableThis && (
            <label className="delete-modal__option">
              <input
                type="radio"
                name="edit-option"
                value="this"
                checked={selectedOption === "this"}
                onChange={(e) => setSelectedOption(e.target.value as RecurringEditOption)}
              />
              <span>{t("calendar.event.editThisOccurrence")}</span>
            </label>
          )}
          {!disableFuture && (
            <label className="delete-modal__option">
              <input
                type="radio"
                name="edit-option"
                value="future"
                checked={selectedOption === "future"}
                onChange={(e) => setSelectedOption(e.target.value as RecurringEditOption)}
              />
              <span>{t("calendar.event.editThisAndFuture")}</span>
            </label>
          )}
          <label className="delete-modal__option">
            <input
              type="radio"
              name="edit-option"
              value="all"
              checked={selectedOption === "all"}
              onChange={(e) => setSelectedOption(e.target.value as RecurringEditOption)}
            />
            <span>{t("calendar.event.editAllOccurrences")}</span>
          </label>
        </div>
      </div>
    </Modal>
  );
};
