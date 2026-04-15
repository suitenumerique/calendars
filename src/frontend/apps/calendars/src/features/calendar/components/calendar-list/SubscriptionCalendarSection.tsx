/**
 * SubscriptionCalendarSection component.
 * Displays subscription calendars in a separate section with sync status.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import type { Subscription } from "../../api";
import { MAX_SUBSCRIPTIONS_PER_USER } from "../../config";
import { CalendarListItem } from "./CalendarListItem";
import { AddSubscriptionModal } from "./AddSubscriptionModal";
import { SubscriptionStatusBadge } from "./SubscriptionStatusBadge";
import { extractCaldavPath } from "./utils";

interface SubscriptionCalendarSectionProps {
  calendars: CalDavCalendar[];
  subscriptions: Subscription[];
  visibleCalendarUrls: Set<string>;
  onToggleVisibility: (url: string) => void;
  onDelete: (subscription: Subscription) => void;
  onReactivate: (subscription: Subscription) => void;
  onEdit?: (calendar: CalDavCalendar) => void;
  onRefresh: () => void;
}

export const SubscriptionCalendarSection = ({
  calendars,
  subscriptions,
  visibleCalendarUrls,
  onToggleVisibility,
  onDelete,
  onReactivate,
  onEdit,
  onRefresh,
}: SubscriptionCalendarSectionProps) => {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(true);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [openMenuUrl, setOpenMenuUrl] = useState<string | null>(null);

  const isLimitReached = subscriptions.length >= MAX_SUBSCRIPTIONS_PER_USER;

  const getSubscriptionForCalendar = (
    calendar: CalDavCalendar,
  ): Subscription | undefined => {
    const calPath = extractCaldavPath(calendar.url);
    if (!calPath) return undefined;
    return subscriptions.find(
      (s) => extractCaldavPath(s.caldav_path) === calPath,
    );
  };

  if (calendars.length === 0 && subscriptions.length === 0) {
    return (
      <div className="calendar-list__section">
        <div className="calendar-list__section-header">
          <button
            className="calendar-list__toggle-btn"
            onClick={() => setIsAddModalOpen(true)}
          >
            <span className="material-icons" style={{ fontSize: "18px" }}>
              link
            </span>
            <span className="calendar-list__section-title">
              {t("calendar.list.subscriptions")}
            </span>
          </button>
          <button
            className="calendar-list__add-btn"
            onClick={() => setIsAddModalOpen(true)}
            title={
              isLimitReached
                ? t("calendar.subscription.add.limitReached")
                : t("calendar.subscription.add.title")
            }
            disabled={isLimitReached}
          >
            <span className="material-icons">add</span>
          </button>
        </div>

        <AddSubscriptionModal
          isOpen={isAddModalOpen}
          onClose={() => setIsAddModalOpen(false)}
          onSuccess={onRefresh}
        />
      </div>
    );
  }

  return (
    <div className="calendar-list__section">
      <div className="calendar-list__section-header">
        <button
          className="calendar-list__toggle-btn"
          onClick={() => setIsExpanded(!isExpanded)}
          aria-expanded={isExpanded}
        >
          <span
            className={`material-icons calendar-list__toggle-icon ${
              isExpanded ? "calendar-list__toggle-icon--expanded" : ""
            }`}
          >
            expand_more
          </span>
          <span className="calendar-list__section-title">
            {t("calendar.list.subscriptions")}
          </span>
        </button>
        <button
          className="calendar-list__add-btn"
          onClick={() => !isLimitReached && setIsAddModalOpen(true)}
          title={
            isLimitReached
              ? t("calendar.subscription.add.limitReached")
              : t("calendar.subscription.add.title")
          }
          disabled={isLimitReached}
        >
          <span className="material-icons">add</span>
        </button>
      </div>

      {isExpanded && (
        <div className="calendar-list__items">
          {calendars.map((calendar) => {
            const subscription = getSubscriptionForCalendar(calendar);
            return (
              <div
                key={calendar.url}
                className="calendar-list__subscription-item"
              >
                <CalendarListItem
                  calendar={calendar}
                  isVisible={visibleCalendarUrls.has(calendar.url)}
                  isMenuOpen={openMenuUrl === calendar.url}
                  onToggleVisibility={onToggleVisibility}
                  onMenuToggle={(url) =>
                    setOpenMenuUrl(openMenuUrl === url ? null : url)
                  }
                  onEdit={() => onEdit?.(calendar)}
                  onDelete={() => subscription && onDelete(subscription)}
                  onCloseMenu={() => setOpenMenuUrl(null)}
                />
                {subscription && (
                  <SubscriptionStatusBadge
                    subscription={subscription}
                    onReactivate={() => onReactivate(subscription)}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      <AddSubscriptionModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onSuccess={onRefresh}
      />
    </div>
  );
};
