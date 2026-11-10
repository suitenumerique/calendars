import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, DropdownMenu } from "@gouvfr-lasuite/ui-components";
import { More, Trash } from "@gouvfr-lasuite/ui-components/icons";

import { getDeleteMenuEntry } from "@/features/calendar/components/calendar-list/utils";

interface CalendarSettingsMenuProps {
  /** Asks to confirm the delete. Set it for the owner only. */
  onDelete?: () => void;
  /** Asks to confirm that the user leaves the calendar. Set it for a sharee only. */
  onLeave?: () => void;
  syncManaged?: boolean;
  /** Asks to confirm the delete for every user of the mailbox. Set it for a mailbox admin only. */
  onDeleteForMailbox?: () => void;
}

/** The menu of a calendar row. It holds the same delete entry as the sidebar menu. */
export const CalendarSettingsMenu = ({
  onDelete,
  onLeave,
  syncManaged,
  onDeleteForMailbox,
}: CalendarSettingsMenuProps) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);

  const entry = getDeleteMenuEntry({ onDelete, onLeave, syncManaged, onDeleteForMailbox });
  if (!entry) return null;

  const options = [{ label: t(entry.labelKey), icon: <Trash />, callback: entry.callback }];

  return (
    <DropdownMenu options={options} isOpen={isOpen} onOpenChange={setIsOpen}>
      <Button
        color="neutral"
        variant="tertiary"
        size="small"
        aria-label={t("calendar.list.options")}
        onClick={() => setIsOpen(!isOpen)}
        icon={<More />}
      />
    </DropdownMenu>
  );
};
