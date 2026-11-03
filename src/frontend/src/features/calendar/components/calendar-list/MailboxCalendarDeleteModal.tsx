import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/ui-components";

import type { MailboxCalendarDeleteModalProps } from "./types";

/** Asks for confirmation before it deletes a mailbox calendar for everyone. */
export const MailboxCalendarDeleteModal = ({
  calendar,
  onConfirm,
  onCancel,
  isLoading,
}: MailboxCalendarDeleteModalProps) => {
  const { t } = useTranslation();

  return (
    <Modal
      isOpen={calendar !== null}
      onClose={onCancel}
      size={ModalSize.SMALL}
      title={t("calendar.deleteMailboxCalendar.title")}
      rightActions={
        <>
          <Button color="neutral" onClick={onCancel} disabled={isLoading}>
            {t("calendar.event.cancel")}
          </Button>
          <Button color="error" onClick={onConfirm} disabled={isLoading}>
            {isLoading ? "..." : t("calendar.deleteMailboxCalendar.confirm")}
          </Button>
        </>
      }
    >
      <p>
        {t("calendar.deleteMailboxCalendar.message", {
          name: calendar?.displayName || "",
          email: calendar?.mailboxEmail || "",
        })}
      </p>
    </Modal>
  );
};
