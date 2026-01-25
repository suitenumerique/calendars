/**
 * DeleteConfirmModal component.
 * Confirms calendar deletion.
 */

import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";

import type { DeleteConfirmModalProps } from "./types";

export const DeleteConfirmModal = ({
  isOpen,
  calendarName,
  onConfirm,
  onCancel,
  isLoading,
}: DeleteConfirmModalProps) => {
  const { t } = useTranslation();

  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      size={ModalSize.SMALL}
      title={t('calendar.deleteCalendar.title')}
      rightActions={
        <>
          <Button color="neutral" onClick={onCancel} disabled={isLoading}>
            {t('calendar.event.cancel')}
          </Button>
          <Button color="error" onClick={onConfirm} disabled={isLoading}>
            {isLoading ? "..." : t('calendar.deleteCalendar.confirm')}
          </Button>
        </>
      }
    >
      <p>{t('calendar.deleteCalendar.message', { name: calendarName })}</p>
    </Modal>
  );
};
