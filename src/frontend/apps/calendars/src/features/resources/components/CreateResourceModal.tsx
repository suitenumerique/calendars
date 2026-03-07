import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Input,
  Modal,
  ModalSize,
  Select,
} from "@gouvfr-lasuite/cunningham-react";

import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";
import { useCreateResource } from "../api/useResources";
import type { ResourceType } from "../types";

type CreateResourceModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
};

export const CreateResourceModal = ({
  isOpen,
  onClose,
  onSuccess,
}: CreateResourceModalProps) => {
  const { t } = useTranslation();
  const createResource = useCreateResource();

  const [name, setName] = useState("");
  const [resourceType, setResourceType] = useState<ResourceType>("ROOM");

  const canSubmit =
    name.trim().length > 0 &&
    !createResource.isPending;

  const handleSubmit = async () => {
    if (!canSubmit) return;

    try {
      await createResource.mutateAsync({
        name: name.trim(),
        resource_type: resourceType,
      });
    } catch {
      addToast(
        <ToasterItem type="error">
          <span>{t("resources.create.error")}</span>
        </ToasterItem>,
      );
      return;
    }
    addToast(
      <ToasterItem type="info">
        <span>{t("resources.create.success")}</span>
      </ToasterItem>,
    );
    onSuccess();
    handleClose();
  };

  const handleClose = () => {
    setName("");
    setResourceType("ROOM");
    onClose();
  };

  const typeOptions = [
    { label: t("resources.types.room"), value: "ROOM" },
    { label: t("resources.types.resource"), value: "RESOURCE" },
  ];

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size={ModalSize.MEDIUM}
      title={t("resources.create.title")}
      actions={
        <>
          <Button color="neutral" onClick={handleClose}>
            {t("common.cancel")}
          </Button>
          <Button
            color="brand"
            onClick={() => void handleSubmit()}
            disabled={!canSubmit}
          >
            {t("resources.create.submit")}
          </Button>
        </>
      }
    >
      <div className="resources-create-modal">
        <Input
          label={t("resources.create.nameLabel")}
          value={name}
          onChange={(e) =>
            setName(
              (e.target as HTMLInputElement).value,
            )
          }
          fullWidth
        />
        <Select
          label={t("resources.create.typeLabel")}
          options={typeOptions}
          value={resourceType}
          onChange={(e) =>
            setResourceType(
              (e.target as HTMLSelectElement).value as ResourceType,
            )
          }
          fullWidth
        />
      </div>
    </Modal>
  );
};
