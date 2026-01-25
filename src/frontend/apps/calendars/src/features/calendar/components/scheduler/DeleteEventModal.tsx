/**
 * DeleteEventModal component.
 * Displays options for deleting recurring events or confirms single event deletion.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";

import type { DeleteEventModalProps, RecurringDeleteOption } from "./types";

export const DeleteEventModal = ({
  isOpen,
  isRecurring,
  onConfirm,
  onCancel,
}: DeleteEventModalProps) => {
  const { t } = useTranslation();
  const [selectedOption, setSelectedOption] =
    useState<RecurringDeleteOption>('this');

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      title={t('calendar.event.deleteConfirm')}
      size={ModalSize.SMALL}
      rightActions={
        <>
          <Button color="neutral" onClick={onCancel}>
            {t('calendar.event.cancel')}
          </Button>
          <Button
            color="error"
            onClick={() => onConfirm(isRecurring ? selectedOption : undefined)}
          >
            {t('calendar.event.delete')}
          </Button>
        </>
      }
    >
      <div className="delete-modal__content">
        {isRecurring ? (
          <>
            <p className="delete-modal__message">
              {t('calendar.event.deleteRecurringPrompt')}
            </p>
            <div className="delete-modal__options">
              <label className="delete-modal__option">
                <input
                  type="radio"
                  name="delete-option"
                  value="this"
                  checked={selectedOption === 'this'}
                  onChange={(e) =>
                    setSelectedOption(e.target.value as RecurringDeleteOption)
                  }
                />
                <span>{t('calendar.event.deleteThisOccurrence')}</span>
              </label>
              <label className="delete-modal__option">
                <input
                  type="radio"
                  name="delete-option"
                  value="future"
                  checked={selectedOption === 'future'}
                  onChange={(e) =>
                    setSelectedOption(e.target.value as RecurringDeleteOption)
                  }
                />
                <span>{t('calendar.event.deleteThisAndFuture')}</span>
              </label>
              <label className="delete-modal__option">
                <input
                  type="radio"
                  name="delete-option"
                  value="all"
                  checked={selectedOption === 'all'}
                  onChange={(e) =>
                    setSelectedOption(e.target.value as RecurringDeleteOption)
                  }
                />
                <span>{t('calendar.event.deleteAllOccurrences')}</span>
              </label>
            </div>
          </>
        ) : (
          <p className="delete-modal__message">
            {t('calendar.event.deleteConfirmMessage')}
          </p>
        )}
      </div>
    </Modal>
  );
};
