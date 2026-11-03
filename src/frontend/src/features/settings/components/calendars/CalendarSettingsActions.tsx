import { useTranslation } from "react-i18next";
import { Button, Icon, IconType } from "@gouvfr-lasuite/ui-components";

import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { isCalendarOwner } from "@/features/calendar/utils/calendar-ownership";
import { CalendarHiddenToggle } from "./CalendarHiddenToggle";
import { MailboxCalendarMenu } from "./MailboxCalendarMenu";

interface CalendarSettingsActionsProps {
  calendar: CalDavCalendar;
  onEdit: (calendar: CalDavCalendar) => void;
  onSetHidden: (calendar: CalDavCalendar, hidden: boolean) => Promise<unknown>;
  /** Set it when the user is an admin of the mailbox of the calendar. */
  onDeleteForMailbox?: (calendar: CalDavCalendar) => void;
  /** Keeps a slot for the mailbox menu, so that the buttons of all rows align. */
  withMenuSlot: boolean;
}

/**
 * The actions of a calendar on the settings page. The user can hide only
 * the calendars that they do not own. Each action has a fixed slot, empty
 * when the action does not apply.
 */
export const CalendarSettingsActions = ({
  calendar,
  onEdit,
  onSetHidden,
  onDeleteForMailbox,
  withMenuSlot,
}: CalendarSettingsActionsProps) => {
  const { t } = useTranslation();
  const hidden = Boolean(calendar.hidden);

  return (
    <>
      <span className="calendar-settings__action">
        <Button
          color="neutral"
          variant="tertiary"
          size="small"
          aria-label={t("calendar.list.edit")}
          title={t("calendar.list.edit")}
          onClick={() => onEdit(calendar)}
          icon={<Icon name="edit" type={IconType.OUTLINED} aria-hidden />}
        />
      </span>
      <span className="calendar-settings__action">
        {!isCalendarOwner(calendar) && (
          <CalendarHiddenToggle hidden={hidden} onToggle={() => onSetHidden(calendar, !hidden)} />
        )}
      </span>
      {withMenuSlot && (
        <span className="calendar-settings__action">
          {onDeleteForMailbox && (
            <MailboxCalendarMenu onDeleteForMailbox={() => onDeleteForMailbox(calendar)} />
          )}
        </span>
      )}
    </>
  );
};
