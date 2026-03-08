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
import { useCreateChannel } from "../api/useChannels";
import type { ChannelRole } from "../types";
import { TokenRevealBox } from "./TokenRevealBox";

type CreateChannelModalProps = {
  isOpen: boolean;
  onClose: () => void;
};

export const CreateChannelModal = ({
  isOpen,
  onClose,
}: CreateChannelModalProps) => {
  const { t } = useTranslation();
  const createChannel = useCreateChannel();

  const [name, setName] = useState("");
  const [role, setRole] = useState<ChannelRole>("reader");
  const [revealedToken, setRevealedToken] = useState<
    string | null
  >(null);

  const canSubmit =
    name.trim().length > 0 && !createChannel.isPending;

  const handleSubmit = async () => {
    if (!canSubmit) return;

    try {
      const result = await createChannel.mutateAsync({
        name: name.trim(),
        role,
      });
      setRevealedToken(result.token);
      addToast(
        <ToasterItem type="info">
          <span>{t("integrations.create.success")}</span>
        </ToasterItem>,
      );
    } catch {
      addToast(
        <ToasterItem type="error">
          <span>{t("integrations.create.error")}</span>
        </ToasterItem>,
      );
    }
  };

  const handleClose = () => {
    setName("");
    setRole("reader");
    setRevealedToken(null);
    onClose();
  };

  const roleOptions = [
    {
      label: t("integrations.roles.reader"),
      value: "reader",
    },
    {
      label: t("integrations.roles.editor"),
      value: "editor",
    },
    {
      label: t("integrations.roles.admin"),
      value: "admin",
    },
  ];

  if (revealedToken) {
    return (
      <Modal
        isOpen={isOpen}
        onClose={handleClose}
        size={ModalSize.MEDIUM}
        title={t("integrations.create.tokenTitle")}
        actions={
          <Button color="brand" onClick={handleClose}>
            {t("common.close")}
          </Button>
        }
      >
        <div className="channel-create-modal">
          <p>{t("integrations.create.tokenWarning")}</p>
          <TokenRevealBox token={revealedToken} />
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size={ModalSize.MEDIUM}
      title={t("integrations.create.title")}
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
            {t("integrations.create.submit")}
          </Button>
        </>
      }
    >
      <div className="channel-create-modal">
        <Input
          label={t("integrations.create.nameLabel")}
          value={name}
          onChange={(e) =>
            setName(
              (e.target as HTMLInputElement).value,
            )
          }
          fullWidth
        />
        <Select
          label={t("integrations.create.roleLabel")}
          options={roleOptions}
          value={role}
          onChange={(e) =>
            setRole(
              (e.target as HTMLSelectElement)
                .value as ChannelRole,
            )
          }
          fullWidth
        />
      </div>
    </Modal>
  );
};
