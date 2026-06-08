import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";
import { useAuth } from "@/features/auth/Auth";
import { caldavServerUrl } from "@/features/calendar/utils/DavClient";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import { useCreateChannel, useRegenerateToken, useUpdateChannel } from "../api/useChannels";
import { ChannelForm } from "./ChannelForm";
import {
  ChannelTypePicker,
  getChannelTypeTitleKey,
  type ChannelPickerType,
} from "./ChannelTypePicker";
import { TokenRevealModal } from "./TokenRevealModal";

import type { Channel, ChannelScopeValue, ChannelType } from "../types";

type ChannelModalProps = {
  isOpen: boolean;
  /** Present for edit mode; omitted for create mode. */
  channel?: Channel;
  onClose: () => void;
};

const DEFAULT_SCOPES: ChannelScopeValue[] = ["calendars:read", "events:read"];

export const ChannelModal = ({ isOpen, channel, onClose }: ChannelModalProps) => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isEdit = channel !== undefined;

  const createChannel = useCreateChannel();
  const updateChannel = useUpdateChannel();
  const regenerateToken = useRegenerateToken();

  const [selectedType, setSelectedType] = useState<ChannelPickerType | null>(null);
  const [name, setName] = useState(channel?.name ?? "");
  const [isActive, setIsActive] = useState(channel?.is_active ?? true);
  const [scopes, setScopes] = useState<ChannelScopeValue[]>(channel?.scopes ?? DEFAULT_SCOPES);
  const [revealedPassword, setRevealedPassword] = useState<string | null>(null);

  // Re-initialize when the parent opens a different target (or clears
  // it), so state from a previous channel doesn't leak into the next
  // one. ``selectedType`` is only used by the create flow, so it's
  // always reset to null here.
  useEffect(() => {
    setSelectedType(null);
    setName(channel?.name ?? "");
    setIsActive(channel?.is_active ?? true);
    setScopes(channel?.scopes ?? DEFAULT_SCOPES);
    setRevealedPassword(null);
  }, [channel]);

  // ical-feed channels have a fixed read-only scope set; the scope
  // editor is meaningless for them (the useful knob is the subscription
  // URL / token, exposed via the regenerate button). Hide it in that
  // case.
  const showScopes = channel?.type !== "ical-feed";

  const isPending = createChannel.isPending || updateChannel.isPending || regenerateToken.isPending;
  const canSubmit = name.trim().length > 0 && scopes.length > 0 && !isPending;

  const handleCreate = async () => {
    if (!canSubmit || !selectedType) return;
    // The picker also advertises "webhook" as a disabled card for UX,
    // so it can never be selected at runtime. Narrow to the backend-
    // accepted set before calling the API.
    if (selectedType !== "caldav") return;
    const backendType: ChannelType = selectedType;
    try {
      const result = await createChannel.mutateAsync({
        name: name.trim(),
        type: backendType,
        scope_level: "user",
        scopes,
      });
      setRevealedPassword(result.password);
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

  const handleSave = async () => {
    if (!canSubmit || !channel) return;
    try {
      await updateChannel.mutateAsync({
        id: channel.id,
        name: name.trim(),
        is_active: isActive,
        scopes,
      });
      addToast(
        <ToasterItem type="info">
          <span>{t("integrations.edit.success")}</span>
        </ToasterItem>,
      );
      onClose();
    } catch {
      addToast(
        <ToasterItem type="error">
          <span>{t("integrations.edit.error")}</span>
        </ToasterItem>,
      );
    }
  };

  const handleRegenerate = async () => {
    if (!channel) return;
    try {
      const result = await regenerateToken.mutateAsync(channel.id);
      setRevealedPassword(result.password);
      addToast(
        <ToasterItem type="info">
          <span>{t("integrations.regenerate.success")}</span>
        </ToasterItem>,
      );
    } catch {
      addToast(
        <ToasterItem type="error">
          <span>{t("integrations.regenerate.error")}</span>
        </ToasterItem>,
      );
    }
  };

  if (revealedPassword) {
    // For CalDAV channels we know how the credentials get consumed
    // (URL + email + password Basic Auth), so we mirror the dialog
    // title to "CalDAV credentials" and surface every piece the user
    // needs in one place. For other channel types (future webhooks
    // etc.) we keep the generic "Integration token" framing.
    const channelType = isEdit ? channel.type : selectedType;
    const isCaldav = channelType === "caldav";
    const tokenTitleKey = isCaldav
      ? "integrations.types.caldav.title"
      : isEdit
        ? "integrations.regenerate.tokenTitle"
        : "integrations.create.tokenTitle";
    const tokenWarningKey = isEdit
      ? "integrations.regenerate.tokenWarning"
      : "integrations.create.tokenWarning";
    // Reuse the exact base URL the in-app CalDAV client targets
    // (``getOrigin()`` honours NEXT_PUBLIC_API_ORIGIN, so this points at
    // the backend that actually serves /caldav, not the SPA origin).
    // Using ``window.location.origin`` here would hand external clients
    // the frontend host, which only serves the SPA in split-origin
    // deployments (and in local dev).
    const caldavUrl = isCaldav ? caldavServerUrl : undefined;
    const caldavUsername = isCaldav ? user?.email : undefined;
    return (
      <TokenRevealModal
        isOpen={isOpen}
        title={t(tokenTitleKey)}
        warning={t(tokenWarningKey)}
        token={revealedPassword}
        caldavUrl={caldavUrl}
        caldavUsername={caldavUsername}
        onClose={onClose}
      />
    );
  }

  if (!isEdit && !selectedType) {
    return (
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={ModalSize.MEDIUM}
        title={t("integrations.create.title")}
      >
        <ChannelTypePicker onSelect={setSelectedType} />
      </Modal>
    );
  }

  const title = isEdit
    ? `${t("integrations.edit.title")} · ${t(
        `integrations.types.${channel.type}.title`,
        channel.type,
      )}`
    : t(getChannelTypeTitleKey(selectedType as ChannelPickerType));

  const actions = isEdit ? (
    <>
      <Button color="neutral" onClick={onClose}>
        {t("common.cancel")}
      </Button>
      <Button color="brand" onClick={() => void handleSave()} disabled={!canSubmit}>
        {t("common.save")}
      </Button>
    </>
  ) : (
    <>
      <Button color="neutral" onClick={() => setSelectedType(null)}>
        {t("common.back")}
      </Button>
      <Button color="brand" onClick={() => void handleCreate()} disabled={!canSubmit}>
        {t("integrations.create.submit")}
      </Button>
    </>
  );

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={ModalSize.MEDIUM}
      title={title}
      actions={actions}
    >
      <ChannelForm
        name={name}
        onNameChange={setName}
        scopes={scopes}
        onScopesChange={setScopes}
        isActive={isEdit ? isActive : undefined}
        onIsActiveChange={isEdit ? setIsActive : undefined}
        onRegenerate={isEdit ? () => void handleRegenerate() : undefined}
        showScopes={showScopes}
        disabled={isPending}
      />
    </Modal>
  );
};
