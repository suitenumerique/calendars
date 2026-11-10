import { useTranslation } from "react-i18next";
import { Mail, Shared } from "@gouvfr-lasuite/ui-components/icons";

import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import { getCalendarGroup } from "@/features/calendar/utils/calendar-ownership";

interface CalendarGroupIconProps {
  calendar: CalDavCalendar;
  className?: string;
}

/**
 * The icon next to a calendar name: an envelope for the calendar of a
 * mailbox the user belongs to, two people for a calendar that others
 * share with the user. A mailbox calendar that an admin shared with the
 * user, outside the mailbox membership, gets the two people. An own
 * calendar gets none.
 */
export const CalendarGroupIcon = ({ calendar, className }: CalendarGroupIconProps) => {
  const { t } = useTranslation();
  const group = getCalendarGroup(calendar);
  if (group === "own") return null;

  const label =
    group === "mailbox"
      ? t("calendar.list.mailboxCalendar", { email: calendar.mailboxEmail })
      : t("calendar.list.sharedCalendar");
  const Icon = group === "mailbox" ? Mail : Shared;
  return (
    <span className={className} role="img" aria-label={label} title={label}>
      <Icon aria-hidden />
    </span>
  );
};
