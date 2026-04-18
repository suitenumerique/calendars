/**
 * SubscriptionCalendarSection component.
 * Displays subscription calendars in a separate section with sync status.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import type { SubscriptionChannel } from "../../api";
import { MAX_SUBSCRIPTIONS_PER_USER } from "../../config";
import { CalendarListItem } from "./CalendarListItem";
import { AddSubscriptionModal } from "./AddSubscriptionModal";
import { EditSubscriptionModal } from "./EditSubscriptionModal";
import { SubscriptionStatusBadge } from "./SubscriptionStatusBadge";
import { extractCaldavPath } from "./utils";

interface SubscriptionCalendarSectionProps {
  calendars: CalDavCalendar[];
  channels: SubscriptionChannel[];
  visibleCalendarUrls: Set<string>;
  onToggleVisibility: (url: string) => void;
  onDelete: (channel: SubscriptionChannel) => void;
  onReactivate: (channel: SubscriptionChannel) => void;
  onRefresh: () => void;
}

export const SubscriptionCalendarSection = ({
  calendars,
  channels,
  visibleCalendarUrls,
  onToggleVisibility,
  onDelete,
  onReactivate,
  onRefresh,
}: SubscriptionCalendarSectionProps) => {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(true);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [editState, setEditState] = useState<{
    channel: SubscriptionChannel;
    calendarColor?: string;
  } | null>(null);
  const [openMenuUrl, setOpenMenuUrl] = useState<string | null>(null);

  const isLimitReached = channels.length >= MAX_SUBSCRIPTIONS_PER_USER;

  const getChannelForCalendar = (calendar: CalDavCalendar) => {
    const calPath = extractCaldavPath(calendar.url);
    if (!calPath) return undefined;
    return channels.find((ch) => calPath === ch.caldav_path);
  };

  if (calendars.length === 0 && channels.length === 0) {
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
            const channel = getChannelForCalendar(calendar);
            return (
              <div key={calendar.url} className="calendar-list__subscription-item">
                <CalendarListItem
                  calendar={calendar}
                  isVisible={visibleCalendarUrls.has(calendar.url)}
                  isMenuOpen={openMenuUrl === calendar.url}
                  onToggleVisibility={onToggleVisibility}
                  onMenuToggle={(url) =>
                    setOpenMenuUrl(openMenuUrl === url ? null : url)
                  }
                  onEdit={() =>
                    channel &&
                    setEditState({
                      channel,
                      calendarColor: calendar.color,
                    })
                  }
                  onDelete={() => channel && onDelete(channel)}
                  onCloseMenu={() => setOpenMenuUrl(null)}
                />
                {channel && (
                  <SubscriptionStatusBadge
                    channel={channel}
                    onReactivate={() => onReactivate(channel)}
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

      <EditSubscriptionModal
        isOpen={editState !== null}
        channel={editState?.channel ?? null}
        calendarColor={editState?.calendarColor}
        onClose={() => setEditState(null)}
        onSuccess={onRefresh}
      />
    </div>
  );
};
