/**
 * CalendarListItem components.
 * Display individual calendar items in the list.
 */

import { useTranslation } from "react-i18next";
import { Checkbox } from "@gouvfr-lasuite/cunningham-react";

import { CalendarItemMenu } from "./CalendarItemMenu";
import type { CalendarListItemProps } from "./types";

/**
 * CalendarListItem - Displays a user-owned calendar.
 */
export const CalendarListItem = ({
  calendar,
  isVisible,
  isMenuOpen,
  isMailboxCalendar = false,
  onToggleVisibility,
  onMenuToggle,
  onEdit,
  onDelete,
  onShare,
  onImport,
  onSubscription,
  onCloseMenu,
}: CalendarListItemProps) => {
  const { t } = useTranslation();

  return (
    <div className="calendar-list__item">
      <div
        className="calendar-list__item-checkbox"
        style={{ "--calendar-color": typeof calendar.color === "string" ? calendar.color : "#3788d8" } as React.CSSProperties}
      >
        <Checkbox
          checked={isVisible}
          onChange={() => onToggleVisibility(calendar.url)}
          label=""
          aria-label={`${t("calendar.list.showCalendar")} ${calendar.displayName || ""}`}
        />
      </div>
      <span
        className="calendar-list__name"
        title={calendar.displayName || undefined}
      >
        {isMailboxCalendar && (
          <span
            className="material-icons calendar-list__mailbox-icon"
            title={t("calendar.list.mailboxCalendar")}
          >
            mail
          </span>
        )}
        {calendar.displayName || "Sans nom"}
      </span>
      <div className="calendar-list__item-actions">
        <CalendarItemMenu
          isOpen={isMenuOpen}
          onOpenChange={(open) =>
            open ? onMenuToggle(calendar.url) : onCloseMenu()
          }
          onEdit={() => onEdit(calendar)}
          onDelete={() => onDelete(calendar)}
          onShare={
            onShare ? () => onShare(calendar) : undefined
          }
          onImport={
            onImport ? () => onImport(calendar) : undefined
          }
          onSubscription={
            onSubscription ? () => onSubscription(calendar) : undefined
          }
        />
      </div>
    </div>
  );
};

