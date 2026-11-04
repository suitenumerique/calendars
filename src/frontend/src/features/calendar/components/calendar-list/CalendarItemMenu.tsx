/**
 * CalendarItemMenu component.
 * Context menu for calendar item actions (edit, hide, delete or leave, subscription).
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  DropdownMenu,
  DropdownMenuOption,
  Icon,
  IconType,
  Button,
} from "@gouvfr-lasuite/ui-components";
import {
  ArrowDown,
  ArrowUp,
  Edit,
  Link as LinkIcon,
  MoreVertical,
  Trash,
  Upload,
} from "@gouvfr-lasuite/ui-components/icons";

import type { CalendarItemMenuProps } from "./types";
import { getDeleteMenuEntry } from "./utils";

export const CalendarItemMenu = ({
  isOpen,
  onOpenChange,
  onEdit,
  onDelete,
  onLeave,
  syncManaged,
  onDeleteForMailbox,
  onHide,
  onShare,
  onImport,
  onSubscription,
  onMoveUp,
  onMoveDown,
}: CalendarItemMenuProps) => {
  const { t } = useTranslation();

  const options: DropdownMenuOption[] = useMemo(() => {
    const items: DropdownMenuOption[] = [
      {
        label: t("calendar.list.edit"),
        icon: <Edit />,
        callback: onEdit,
      },
    ];

    if (onShare) {
      items.push({
        label: t("calendar.list.share"),
        icon: <Icon name="person_add" type={IconType.OUTLINED} aria-hidden />,
        callback: onShare,
      });
    }

    if (onImport) {
      items.push({
        label: t("calendar.list.import"),
        icon: <Upload />,
        callback: onImport,
      });
    }

    if (onSubscription) {
      items.push({
        label: t("calendar.list.subscription"),
        icon: <LinkIcon />,
        callback: onSubscription,
      });
    }

    if (onMoveUp) {
      items.push({
        label: t("calendar.list.moveUp"),
        icon: <ArrowUp />,
        callback: onMoveUp,
      });
    }

    if (onMoveDown) {
      items.push({
        label: t("calendar.list.moveDown"),
        icon: <ArrowDown />,
        callback: onMoveDown,
      });
    }

    if (onHide) {
      items.push({
        label: t("calendar.list.hide"),
        icon: <Icon name="visibility_off" type={IconType.OUTLINED} aria-hidden />,
        callback: onHide,
      });
    }

    const deleteEntry = getDeleteMenuEntry({ onDelete, onLeave, syncManaged, onDeleteForMailbox });
    if (deleteEntry) {
      items.push({
        label: t(deleteEntry.labelKey),
        icon: <Trash />,
        callback: deleteEntry.callback,
      });
    }

    return items;
  }, [
    t,
    onEdit,
    onDelete,
    onLeave,
    syncManaged,
    onDeleteForMailbox,
    onHide,
    onShare,
    onImport,
    onSubscription,
    onMoveUp,
    onMoveDown,
  ]);

  return (
    <DropdownMenu options={options} isOpen={isOpen} onOpenChange={onOpenChange}>
      <Button
        className="calendar-list__options-btn"
        aria-label={t("calendar.list.options")}
        color="brand"
        variant="tertiary"
        size="small"
        onClick={() => onOpenChange(!isOpen)}
        icon={<MoreVertical />}
      />
    </DropdownMenu>
  );
};
