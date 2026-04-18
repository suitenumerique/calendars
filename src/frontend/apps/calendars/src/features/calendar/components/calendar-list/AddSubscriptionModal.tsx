/**
 * AddSubscriptionModal component.
 * Simple modal with a URL input to add an external calendar subscription.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize, Input } from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";

import { useCreateSubscription } from "../../hooks/useCalendars";
import { ColorPicker } from "./ColorPicker";
import { DEFAULT_COLORS } from "./constants";

interface AddSubscriptionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export const AddSubscriptionModal = ({
  isOpen,
  onClose,
  onSuccess,
}: AddSubscriptionModalProps) => {
  const { t } = useTranslation();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [color, setColor] = useState(DEFAULT_COLORS[0]);
  const createMutation = useCreateSubscription();

  const handleSubmit = async () => {
    if (!url.trim()) return;

    try {
      await createMutation.mutateAsync({
        name: name.trim() || url.trim(),
        sourceUrl: url.trim(),
        color,
      });
      setUrl("");
      setName("");
      setColor(DEFAULT_COLORS[0]);
      onSuccess?.();
      onClose();
    } catch {
      // Error is available via createMutation.error
    }
  };

  const handleClose = () => {
    setUrl("");
    setName("");
    setColor(DEFAULT_COLORS[0]);
    createMutation.reset();
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size={ModalSize.MEDIUM}
      title={t("calendar.subscription.add.title")}
      actions={
        <>
          <Button
            color="neutral"
            onClick={handleClose}
            disabled={createMutation.isPending}
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!url.trim() || createMutation.isPending}
          >
            {createMutation.isPending ? (
              <Spinner />
            ) : (
              t("calendar.subscription.add.submit")
            )}
          </Button>
        </>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <p className="calendar-modal__description">
          {t("calendar.subscription.add.description")}
        </p>

        <Input
          label={t("calendar.subscription.add.urlLabel")}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/calendar.ics"
          fullWidth
          state={createMutation.isError ? "error" : "default"}
          text={
            createMutation.isError
              ? t("calendar.subscription.add.error")
              : undefined
          }
        />

        <Input
          label={t("calendar.subscription.add.nameLabel")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("calendar.subscription.add.namePlaceholder")}
          fullWidth
        />

        <ColorPicker value={color} onChange={setColor} />
      </div>
    </Modal>
  );
};
