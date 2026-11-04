import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, DropdownMenu } from "@gouvfr-lasuite/ui-components";
import { More, Trash } from "@gouvfr-lasuite/ui-components/icons";

interface MailboxCalendarMenuProps {
  onDeleteForMailbox: () => void;
}

/** The menu of a mailbox calendar for a mailbox admin. */
export const MailboxCalendarMenu = ({ onDeleteForMailbox }: MailboxCalendarMenuProps) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);

  const options = [
    {
      label: t("calendar.list.deleteForMailbox"),
      icon: <Trash />,
      callback: onDeleteForMailbox,
    },
  ];

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
