/**
 * SubscriptionStatusBadge component.
 * Shows sync status (ok/error/stopped) for a subscription calendar.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";

import type { Subscription } from "../../api";

interface SubscriptionStatusBadgeProps {
  subscription: Subscription;
  onReactivate: () => void;
}

export const SubscriptionStatusBadge = ({
  subscription,
  onReactivate,
}: SubscriptionStatusBadgeProps) => {
  const { t } = useTranslation();
  const [showError, setShowError] = useState(false);

  if (subscription.last_sync_status === "stopped") {
    return (
      <div className="subscription-status subscription-status--stopped">
        <span
          className="subscription-status__icon material-icons"
          title={t("calendar.subscription.status.stopped")}
        >
          block
        </span>
        {showError && (
          <div className="subscription-status__error">
            <p>
              {subscription.last_sync_error ||
                t("calendar.subscription.status.stoppedDescription")}
            </p>
            <Button size="small" onClick={onReactivate}>
              {t("calendar.subscription.status.reactivate")}
            </Button>
          </div>
        )}
        <button
          className="subscription-status__toggle"
          onClick={() => setShowError(!showError)}
          title={t("calendar.subscription.status.viewError")}
        >
          <span className="material-icons" style={{ fontSize: "14px" }}>
            {showError ? "expand_less" : "expand_more"}
          </span>
        </button>
      </div>
    );
  }

  if (subscription.last_sync_status === "ok") {
    return null;
  }

  if (subscription.last_sync_status === "error") {
    return (
      <div className="subscription-status subscription-status--error">
        <button
          className="subscription-status__icon material-icons"
          title={
            subscription.last_sync_error ||
            t("calendar.subscription.status.error")
          }
          onClick={() => setShowError(!showError)}
          style={{
            cursor: "pointer",
            background: "none",
            border: "none",
            padding: 0,
          }}
          aria-label={t("calendar.subscription.status.viewError")}
        >
          warning
        </button>
        {showError && (
          <div className="subscription-status__error">
            <p>{subscription.last_sync_error}</p>
          </div>
        )}
      </div>
    );
  }

  if (subscription.last_sync_status === "pending") {
    return (
      <div className="subscription-status subscription-status--pending">
        <span
          className="subscription-status__icon material-icons"
          title={t("calendar.subscription.status.pending")}
        >
          sync
        </span>
      </div>
    );
  }

  return null;
};
