/**
 * CalendarListItem components.
 * Display individual calendar items in the list.
 */

import { useTranslation } from "react-i18next";
import { Checkbox } from "@gouvfr-lasuite/cunningham-react";

import { CalendarItemMenu } from "./CalendarItemMenu";
import type {
  CalendarListItemProps,
  SharedCalendarListItemProps,
} from "./types";

/**
 * CalendarListItem - Displays a user-owned calendar.
 */
export const CalendarListItem = ({
  calendar,
  isVisible,
  isMenuOpen,
  onToggleVisibility,
  onMenuToggle,
  onEdit,
  onDelete,
  onImport,
  onSubscription,
  onCloseMenu,
}: CalendarListItemProps) => {
  const { t } = useTranslation();

  return (
    <div className="calendar-list__item">
      <div
        className="calendar-list__item-checkbox"
        style={{ "--calendar-color": calendar.color } as React.CSSProperties}
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

/**
 * SharedCalendarListItem - Displays a shared calendar.
 */
export const SharedCalendarListItem = ({
  calendar,
  isVisible,
  onToggleVisibility,
}: SharedCalendarListItemProps) => {
  const { t } = useTranslation();

  return (
    <div className="calendar-list__item">
      <div
        className="calendar-list__item-checkbox"
        style={{ "--calendar-color": calendar.color } as React.CSSProperties}
      >
        <Checkbox
          checked={isVisible}
          onChange={() => onToggleVisibility(String(calendar.id))}
          label=""
          aria-label={`${t("calendar.list.showCalendar")} ${calendar.name}`}
        />
        <span
          className="calendar-list__color"
          style={{ backgroundColor: calendar.color }}
        />
      </div>
      <span className="calendar-list__name" title={calendar.name}>
        {calendar.name}
      </span>
    </div>
  );
};
