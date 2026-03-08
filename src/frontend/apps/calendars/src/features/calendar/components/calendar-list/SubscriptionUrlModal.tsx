/**
 * SubscriptionUrlModal component.
 * Displays the subscription URL for iCal export with copy and regenerate options.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";

import {
  useCreateICalFeedChannel,
  useDeleteICalFeedChannel,
  useICalFeedChannel,
} from "../../hooks/useCalendars";

interface SubscriptionUrlModalProps {
  isOpen: boolean;
  caldavPath: string;
  calendarName: string;
  onClose: () => void;
}

export const SubscriptionUrlModal = ({
  isOpen,
  caldavPath,
  calendarName,
  onClose,
}: SubscriptionUrlModalProps) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [showRegenerateConfirm, setShowRegenerateConfirm] = useState(false);
  const [hasTriedCreate, setHasTriedCreate] = useState(false);

  const { channel, channelError, isLoading } = useICalFeedChannel(caldavPath);
  const createChannel = useCreateICalFeedChannel();
  const deleteChannelMutation = useDeleteICalFeedChannel();

  // Use channel from query or from mutation result (whichever is available)
  const displayChannel = channel || createChannel.data;
  const displayUrl = displayChannel?.url;
  // Show error from channel fetch or from creation failure
  const hasRealError =
    channelError || (createChannel.error && hasTriedCreate);
  const isRegenerating =
    deleteChannelMutation.isPending || createChannel.isPending;
  const showLoading = isLoading || createChannel.isPending;

  // Get appropriate error message based on error type
  const getErrorMessage = (): string => {
    if (channelError) {
      switch (channelError.type) {
        case "permission_denied":
          return t("calendar.subscription.errorPermission");
        case "network_error":
          return t("calendar.subscription.errorNetwork");
        case "server_error":
          return t("calendar.subscription.errorServer");
        default:
          return t("calendar.subscription.error");
      }
    }
    return t("calendar.subscription.error");
  };

  // Reset hasTriedCreate when modal closes
  useEffect(() => {
    if (!isOpen) {
      setHasTriedCreate(false);
    }
  }, [isOpen]);

  // Create channel on first open if none exists (only try once)
  useEffect(() => {
    if (
      isOpen &&
      !channel &&
      !isLoading &&
      !createChannel.isPending &&
      !hasTriedCreate
    ) {
      setHasTriedCreate(true);
      createChannel.mutate({ caldavPath, calendarName });
    }
  }, [
    isOpen,
    channel,
    isLoading,
    createChannel,
    caldavPath,
    calendarName,
    hasTriedCreate,
  ]);

  const handleCopy = async () => {
    if (!displayUrl) return;

    try {
      await navigator.clipboard.writeText(displayUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      const textArea = document.createElement("textarea");
      textArea.value = displayUrl;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand("copy");
      document.body.removeChild(textArea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleRegenerate = async () => {
    setShowRegenerateConfirm(false);
    const channelId = displayChannel?.id;
    if (!channelId) return;
    await deleteChannelMutation.mutateAsync(channelId);
    await createChannel.mutateAsync({ caldavPath, calendarName });
  };

  return (
    <>
      <Modal
        isOpen={isOpen && !showRegenerateConfirm}
        onClose={onClose}
        size={ModalSize.MEDIUM}
        title={t("calendar.subscription.title")}
        rightActions={
          <Button color="brand" onClick={onClose}>
            {t("calendar.subscription.close")}
          </Button>
        }
      >
        <div className="subscription-modal">
          <p className="subscription-modal__description">
            {t("calendar.subscription.description", { name: calendarName })}
          </p>

          {showLoading ? (
            <div className="subscription-modal__loading">
              {t("calendar.subscription.loading")}
            </div>
          ) : hasRealError && !displayUrl ? (
            <div className="subscription-modal__error">
              {getErrorMessage()}
            </div>
          ) : displayUrl ? (
            <>
              <div className="subscription-modal__url-container">
                <input
                  type="text"
                  readOnly
                  value={displayUrl}
                  className="subscription-modal__url-input"
                  onClick={(e) => (e.target as HTMLInputElement).select()}
                />
                <Button
                  color="brand"
                  onClick={handleCopy}
                  disabled={isRegenerating}
                >
                  {copied
                    ? t("calendar.subscription.copied")
                    : t("calendar.subscription.copy")}
                </Button>
              </div>

              <div className="subscription-modal__warning">
                <span className="material-icons subscription-modal__warning-icon">
                  warning
                </span>
                <p>{t("calendar.subscription.warning")}</p>
              </div>

              <div className="subscription-modal__actions">
                <Button
                  color="neutral"
                  onClick={() => setShowRegenerateConfirm(true)}
                  disabled={isRegenerating}
                >
                  {t("calendar.subscription.regenerate")}
                </Button>
              </div>
            </>
          ) : null}
        </div>
      </Modal>

      {/* Regenerate confirmation modal */}
      <Modal
        isOpen={showRegenerateConfirm}
        onClose={() => setShowRegenerateConfirm(false)}
        size={ModalSize.SMALL}
        title={t("calendar.subscription.regenerateConfirm.title")}
        rightActions={
          <>
            <Button
              color="neutral"
              onClick={() => setShowRegenerateConfirm(false)}
              disabled={isRegenerating}
            >
              {t("calendar.event.cancel")}
            </Button>
            <Button
              color="error"
              onClick={handleRegenerate}
              disabled={isRegenerating}
            >
              {isRegenerating
                ? "..."
                : t("calendar.subscription.regenerateConfirm.confirm")}
            </Button>
          </>
        }
      >
        <p>{t("calendar.subscription.regenerateConfirm.message")}</p>
      </Modal>
    </>
  );
};
