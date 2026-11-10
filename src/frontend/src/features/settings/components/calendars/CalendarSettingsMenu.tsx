import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, DropdownMenu } from "@gouvfr-lasuite/ui-components";
import { More, Trash } from "@gouvfr-lasuite/ui-components/icons";

import { getDeleteMenuEntry } from "@/features/calendar/components/calendar-list/utils";

interface CalendarSettingsMenuProps {
  /** Asks to confirm that the user leaves the calendar. Set it for a sharee only. */
  onLeave?: () => void;
  /** Deletes the calendar for every user of the mailbox. Set it for a mailbox admin only. */
  onDeleteForMailbox?: () => void;
}

/** The menu of a calendar row. It holds the leave action, or the delete action of a mailbox admin. */
export const CalendarSettingsMenu = ({
  onLeave,
  onDeleteForMailbox,
}: CalendarSettingsMenuProps) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);

  const entry = getDeleteMenuEntry({ onLeave, onDeleteForMailbox });
  if (!entry?.callback) return null;

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
