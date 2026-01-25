/**
 * CalendarListItem components.
 * Display individual calendar items in the list.
 */

import { useTranslation } from "react-i18next";
import { Checkbox } from "@gouvfr-lasuite/cunningham-react";

import { CalendarItemMenu } from "./CalendarItemMenu";
import type { CalendarListItemProps, SharedCalendarListItemProps } from "./types";

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
  onSubscription,
  onCloseMenu,
}: CalendarListItemProps) => {
  const { t } = useTranslation();

  return (
    <div className="calendar-list__item">
      <div className="calendar-list__item-checkbox">
        <Checkbox
          checked={isVisible}
          onChange={() => onToggleVisibility(calendar.url)}
          label=""
          aria-label={`${t('calendar.list.showCalendar')} ${calendar.displayName || ''}`}
        />
        <span
          className="calendar-list__color"
          style={{ backgroundColor: calendar.color }}
        />
      </div>
      <span
        className="calendar-list__name"
        title={calendar.displayName || undefined}
      >
        {calendar.displayName || 'Sans nom'}
      </span>
      <div className="calendar-list__item-actions">
        <button
          className="calendar-list__options-btn"
          onClick={(e) => onMenuToggle(calendar.url, e)}
          aria-label="Options"
        >
          <span className="material-icons">more_horiz</span>
        </button>
        {isMenuOpen && (
          <CalendarItemMenu
            onEdit={() => onEdit(calendar)}
            onDelete={() => onDelete(calendar)}
            onSubscription={onSubscription ? () => onSubscription(calendar) : undefined}
            onClose={onCloseMenu}
          />
        )}
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
      <div className="calendar-list__item-checkbox">
        <Checkbox
          checked={isVisible}
          onChange={() => onToggleVisibility(String(calendar.id))}
          label=""
          aria-label={`${t('calendar.list.showCalendar')} ${calendar.name}`}
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
