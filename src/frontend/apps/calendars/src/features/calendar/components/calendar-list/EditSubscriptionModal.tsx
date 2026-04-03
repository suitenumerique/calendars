/**
 * EditSubscriptionModal component.
 * Modal for editing a subscription channel's name, source URL, and color.
 */

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Input,
  Modal,
  ModalSize,
} from "@gouvfr-lasuite/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";

import { useUpdateSubscriptionChannel } from "../../hooks/useCalendars";
import type { SubscriptionChannel } from "../../api";
import { ColorPicker } from "./ColorPicker";
import { DEFAULT_COLORS } from "./constants";

interface EditSubscriptionModalProps {
  isOpen: boolean;
  channel: SubscriptionChannel | null;
  calendarColor?: string;
  onClose: () => void;
  onSuccess?: () => void;
}

export const EditSubscriptionModal = ({
  isOpen,
  channel,
  calendarColor,
  onClose,
  onSuccess,
}: EditSubscriptionModalProps) => {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [color, setColor] = useState(DEFAULT_COLORS[0]);
  const updateMutation = useUpdateSubscriptionChannel();

  useEffect(() => {
    if (isOpen && channel) {
      setName(channel.name ?? "");
      setSourceUrl(channel.source_url ?? "");
      setColor(calendarColor || DEFAULT_COLORS[0]);
      updateMutation.reset();
    }
  }, [isOpen, channel]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async () => {
    if (!channel || !name.trim() || !sourceUrl.trim()) return;

    const params: { name?: string; sourceUrl?: string; color?: string } = {};

    if (name.trim() !== channel.name) {
      params.name = name.trim();
    }
    if (sourceUrl.trim() !== channel.source_url) {
      params.sourceUrl = sourceUrl.trim();
    }
    if (color !== (calendarColor || DEFAULT_COLORS[0])) {
      params.color = color;
    }

    if (Object.keys(params).length === 0) {
      onClose();
      return;
    }

    try {
      await updateMutation.mutateAsync({
        channelId: channel.id,
        params,
      });
      onSuccess?.();
      onClose();
    } catch {
      // Error is available via updateMutation.error
    }
  };

  const handleClose = () => {
    updateMutation.reset();
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size={ModalSize.MEDIUM}
      title={t("calendar.subscription.edit.title")}
      actions={
        <>
          <Button
            color="neutral"
            onClick={handleClose}
            disabled={updateMutation.isPending}
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={
              !name.trim() ||
              !sourceUrl.trim() ||
              updateMutation.isPending
            }
          >
            {updateMutation.isPending ? (
              <Spinner />
            ) : (
              t("calendar.subscription.edit.save")
            )}
          </Button>
        </>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <Input
          label={t("calendar.subscription.add.nameLabel")}
          value={name}
          onChange={(e) => setName(e.target.value ?? "")}
          fullWidth
        />

        <Input
          label={t("calendar.subscription.add.urlLabel")}
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value ?? "")}
          placeholder="https://example.com/calendar.ics"
          fullWidth
          state={updateMutation.isError ? "error" : "default"}
          text={
            updateMutation.isError
              ? t("calendar.subscription.edit.error")
              : undefined
          }
        />

        <ColorPicker value={color} onChange={setColor} />
      </div>
    </Modal>
  );
};
