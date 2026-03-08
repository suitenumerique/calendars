import { useTranslation } from "react-i18next";
import {
  Button,
  Modal,
  ModalSize,
} from "@gouvfr-lasuite/cunningham-react";

import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";
import { useDeleteChannel } from "../api/useChannels";

type DeleteChannelModalProps = {
  isOpen: boolean;
  id: string;
  name: string;
  onClose: () => void;
};

export const DeleteChannelModal = ({
  isOpen,
  id,
  name,
  onClose,
}: DeleteChannelModalProps) => {
  const { t } = useTranslation();
  const deleteChannel = useDeleteChannel();

  const handleDelete = async () => {
    try {
      await deleteChannel.mutateAsync(id);
      addToast(
        <ToasterItem type="info">
          <span>{t("integrations.delete.success")}</span>
        </ToasterItem>,
      );
      onClose();
    } catch {
      addToast(
        <ToasterItem type="error">
          <span>{t("integrations.delete.error")}</span>
        </ToasterItem>,
      );
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={ModalSize.SMALL}
      title={t("integrations.delete.title")}
      actions={
        <>
          <Button color="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            color="error"
            onClick={() => void handleDelete()}
            disabled={deleteChannel.isPending}
          >
            {t("integrations.delete.confirm")}
          </Button>
        </>
      }
    >
      <p>
        {t("integrations.delete.message", { name })}
      </p>
    </Modal>
  );
};
