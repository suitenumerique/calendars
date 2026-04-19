import { useTranslation } from "react-i18next";
import {
  Button,
  Modal,
  ModalSize,
} from "@gouvfr-lasuite/cunningham-react";

import { TokenRevealBox } from "./TokenRevealBox";

type TokenRevealModalProps = {
  isOpen: boolean;
  title: string;
  warning: string;
  token: string;
  onClose: () => void;
};

export const TokenRevealModal = ({
  isOpen,
  title,
  warning,
  token,
  onClose,
}: TokenRevealModalProps) => {
  const { t } = useTranslation();

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={ModalSize.MEDIUM}
      title={title}
      actions={
        <Button color="brand" onClick={onClose}>
          {t("common.close")}
        </Button>
      }
    >
      <div className="channel-edit-modal">
        <p>{warning}</p>
        <TokenRevealBox token={token} />
      </div>
    </Modal>
  );
};
