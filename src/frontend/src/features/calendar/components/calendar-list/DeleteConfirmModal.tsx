/**
 * DeleteConfirmModal component.
 * Confirms that the owner deletes a calendar, or that a sharee leaves it.
 */

import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/ui-components";

import { getCalendarDeleteMode } from "@/features/calendar/utils/calendar-ownership";
import type { DeleteConfirmModalProps } from "./types";

export const DeleteConfirmModal = ({
  calendar,
  onConfirm,
  onCancel,
  isLoading,
}: DeleteConfirmModalProps) => {
  const { t } = useTranslation();

  const mode = calendar ? getCalendarDeleteMode(calendar) : "delete";
  const keyPrefix = mode === "leave" ? "calendar.leaveCalendar" : "calendar.deleteCalendar";
  const name = calendar?.displayName || "";

  return (
    <Modal
      isOpen={calendar !== null}
      onClose={onCancel}
      size={ModalSize.SMALL}
      title={t(`${keyPrefix}.title`)}
      rightActions={
        <>
          <Button color="neutral" onClick={onCancel} disabled={isLoading}>
            {t("calendar.event.cancel")}
          </Button>
          <Button color="error" onClick={onConfirm} disabled={isLoading}>
            {isLoading ? "..." : t(`${keyPrefix}.confirm`)}
          </Button>
        </>
      }
    >
      <p>{t(`${keyPrefix}.message`, { name })}</p>
      {mode === "delete-shared" && <p>{t("calendar.deleteCalendar.sharedWarning")}</p>}
    </Modal>
  );
};
