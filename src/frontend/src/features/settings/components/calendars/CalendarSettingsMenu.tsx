import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, DropdownMenu } from "@gouvfr-lasuite/ui-components";
import { More, Trash } from "@gouvfr-lasuite/ui-components/icons";

interface CalendarSettingsMenuProps {
  /** Asks to confirm that the user leaves the calendar. Set it for a sharee only. */
  onLeave?: () => void;
  /** Deletes the calendar for every user of the mailbox. Set it for a mailbox admin only. */
  onDeleteForMailbox?: () => void;
}

/** The menu of a calendar row. The delete for every mailbox user replaces the leave action. */
export const CalendarSettingsMenu = ({
  onLeave,
  onDeleteForMailbox,
}: CalendarSettingsMenuProps) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);

  const callback = onDeleteForMailbox ?? onLeave;
  if (!callback) return null;

  const labelKey = onDeleteForMailbox
    ? "calendar.list.deleteForMailbox"
    : "calendar.list.leaveCalendar";
  const options = [{ label: t(labelKey), icon: <Trash />, callback }];

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
