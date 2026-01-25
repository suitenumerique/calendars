/**
 * SubscriptionUrlModal component.
 * Displays the subscription URL for iCal export with copy and regenerate options.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";

import {
  useCreateSubscriptionToken,
  useDeleteSubscriptionToken,
  useSubscriptionToken,
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

  const { token, tokenError, isLoading } = useSubscriptionToken(caldavPath);
  const createToken = useCreateSubscriptionToken();
  const deleteToken = useDeleteSubscriptionToken();

  // Use token from query or from mutation result (whichever is available)
  const displayToken = token || createToken.data;
  // Show error from token fetch or from creation failure
  const hasRealError = tokenError || (createToken.error && hasTriedCreate);
  const isRegenerating = deleteToken.isPending || createToken.isPending;
  const showLoading = isLoading || createToken.isPending;

  // Get appropriate error message based on error type
  const getErrorMessage = (): string => {
    if (tokenError) {
      switch (tokenError.type) {
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

  // Create token on first open if none exists (only try once)
  // We also try to create if there was an error (404 means no token exists)
  useEffect(() => {
    if (
      isOpen &&
      !token &&
      !isLoading &&
      !createToken.isPending &&
      !hasTriedCreate
    ) {
      setHasTriedCreate(true);
      createToken.mutate({ caldavPath, calendarName });
    }
  }, [isOpen, token, isLoading, createToken, caldavPath, calendarName, hasTriedCreate]);

  const handleCopy = async () => {
    const url = displayToken?.url;
    if (!url) return;

    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      const textArea = document.createElement("textarea");
      textArea.value = url;
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
    await deleteToken.mutateAsync(caldavPath);
    await createToken.mutateAsync({ caldavPath, calendarName });
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
          ) : hasRealError && !displayToken ? (
            <div className="subscription-modal__error">
              {getErrorMessage()}
            </div>
          ) : displayToken?.url ? (
            <>
              <div className="subscription-modal__url-container">
                <input
                  type="text"
                  readOnly
                  value={displayToken.url}
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
