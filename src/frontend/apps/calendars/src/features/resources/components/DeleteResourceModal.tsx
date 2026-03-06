import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";

import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";
import { useDeleteResource } from "../api/useResources";

type DeleteResourceModalProps = {
  isOpen: boolean;
  id: string;
  name: string;
  onClose: () => void;
  onSuccess: () => void;
};

export const DeleteResourceModal = ({
  isOpen,
  id,
  name,
  onClose,
  onSuccess,
}: DeleteResourceModalProps) => {
  const { t } = useTranslation();
  const deleteResource = useDeleteResource();

  const handleDelete = async () => {
    try {
      await deleteResource.mutateAsync(id);
      addToast(
        <ToasterItem type="info">
          <span>{t("resources.delete.success")}</span>
        </ToasterItem>,
      );
      onSuccess();
      onClose();
    } catch {
      addToast(
        <ToasterItem type="error">
          <span>{t("resources.delete.error")}</span>
        </ToasterItem>,
      );
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={ModalSize.SMALL}
      title={t("resources.delete.title")}
      actions={
        <>
          <Button color="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            color="error"
            onClick={() => void handleDelete()}
            disabled={deleteResource.isPending}
          >
            {t("resources.delete.confirm")}
          </Button>
        </>
      }
    >
      <p>
        {t("resources.delete.message", { name })}
      </p>
    </Modal>
  );
};
