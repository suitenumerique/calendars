/**
 * CalendarItemMenu component.
 * Context menu for calendar item actions (edit, delete).
 */

import { useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";

import type { CalendarItemMenuProps } from "./types";

export const CalendarItemMenu = ({
  onEdit,
  onDelete,
  onSubscription,
  onClose,
}: CalendarItemMenuProps) => {
  const { t } = useTranslation();
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose]);

  const handleEdit = () => {
    onEdit();
    onClose();
  };

  const handleDelete = () => {
    onDelete();
    onClose();
  };

  const handleSubscription = () => {
    if (onSubscription) {
      onSubscription();
      onClose();
    }
  };

  return (
    <div ref={menuRef} className="calendar-list__menu">
      <button className="calendar-list__menu-item" onClick={handleEdit}>
        <span className="material-icons">edit</span>
        {t('calendar.list.edit')}
      </button>
      {onSubscription && (
        <button className="calendar-list__menu-item" onClick={handleSubscription}>
          <span className="material-icons">link</span>
          {t('calendar.list.subscription')}
        </button>
      )}
      <button
        className="calendar-list__menu-item calendar-list__menu-item--danger"
        onClick={handleDelete}
      >
        <span className="material-icons">delete</span>
        {t('calendar.list.delete')}
      </button>
    </div>
  );
};
