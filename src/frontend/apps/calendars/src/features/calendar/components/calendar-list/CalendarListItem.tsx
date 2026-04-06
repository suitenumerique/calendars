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
  mailboxEmail,
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

  const calendarColor = typeof calendar.color === "string" ? calendar.color : "#3788d8";

  return (
    <div
      className={`calendar-list__item ${
        isMenuOpen ? "calendar-list__item--menu-open" : ""
      }`}
    >
      <div
        className="calendar-list__item-checkbox"
        style={{ "--calendar-color": calendarColor } as React.CSSProperties}
      >
        <Checkbox
          checked={isVisible}
          onChange={() => onToggleVisibility(calendar.url)}
          label=""
          aria-label={`${t("calendar.list.showCalendar")} ${calendar.displayName || ""}`}
        />
      </div>
      <div className="calendar-list__name-wrapper">
        <span
          className="calendar-list__name"
          title={calendar.displayName || undefined}
        >
          {calendar.displayName || t("calendar.list.unnamed")}
        </span>
        {mailboxEmail && (
          <span
            className="material-icons calendar-list__mailbox-icon"
            title={t("calendar.list.mailboxCalendar", { email: mailboxEmail })}
            aria-label={t("calendar.list.mailboxCalendar", { email: mailboxEmail })}
          >
            mail
          </span>
        )}
      </div>
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

