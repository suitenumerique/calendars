/**
 * CalendarItemMenu component.
 * Context menu for calendar item actions (edit, delete, subscription).
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { DropdownMenu, DropdownMenuOption } from "@gouvfr-lasuite/ui-kit";

import type { CalendarItemMenuProps } from "./types";
import { Button } from "@gouvfr-lasuite/cunningham-react";

export const CalendarItemMenu = ({
  isOpen,
  onOpenChange,
  onEdit,
  onDelete,
  onSubscription,
}: CalendarItemMenuProps) => {
  const { t } = useTranslation();

  const options: DropdownMenuOption[] = useMemo(() => {
    const items: DropdownMenuOption[] = [
      {
        label: t("calendar.list.edit"),
        icon: <span className="material-icons">edit</span>,
        callback: onEdit,
      },
    ];

    if (onSubscription) {
      items.push({
        label: t("calendar.list.subscription"),
        icon: <span className="material-icons">link</span>,
        callback: onSubscription,
      });
    }

    items.push({
      label: t("calendar.list.delete"),
      icon: <span className="material-icons">delete</span>,
      callback: onDelete,
    });

    return items;
  }, [t, onEdit, onDelete, onSubscription]);

  return (
    <DropdownMenu options={options} isOpen={isOpen} onOpenChange={onOpenChange}>
      <Button
        className="calendar-list__options-btn"
        aria-label={t("calendar.list.options")}
        color="brand"
        variant="tertiary"
        size="small"
        onClick={() => onOpenChange(!isOpen)}
        icon={<span className="material-icons">more_vert</span>}
      />
    </DropdownMenu>
  );
};
