import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { IcsAttendee } from "ts-ics";
import { useCalendarContext } from "../../../contexts/CalendarContext";
import { useFreeBusy } from "../hooks/useFreeBusy";
import { FreeBusyTimeline } from "../FreeBusyTimeline";
import { SectionRow } from "./SectionRow";
import {
  formatDateTimeLocal,
  parseDateTimeLocal,
} from "../utils/dateFormatters";

interface FreeBusySectionProps {
  attendees: IcsAttendee[];
  resourceEmails?: string[];
  resourceNames?: Record<string, string>;
  organizerEmail?: string;
  startDateTime: string;
  endDateTime: string;
  onStartChange: (value: string) => void;
  onEndChange: (value: string) => void;
  alwaysOpen?: boolean;
}

export const FreeBusySection = ({
  attendees,
  resourceEmails,
  resourceNames,
  organizerEmail,
  startDateTime,
  endDateTime,
  onStartChange,
  onEndChange,
  alwaysOpen,
}: FreeBusySectionProps) => {
  const { t } = useTranslation();
  const { caldavService } = useCalendarContext();

  const eventStart = useMemo(
    () => parseDateTimeLocal(startDateTime),
    [startDateTime],
  );
  const eventEnd = useMemo(
    () => parseDateTimeLocal(endDateTime),
    [endDateTime],
  );

  const allEmails = useMemo(
    () => [
      ...attendees.map((a) => a.email.toLowerCase()),
      ...(resourceEmails ?? []).map((e) => e.toLowerCase()),
    ],
    [attendees, resourceEmails],
  );

  const { data, isLoading } = useFreeBusy({
    caldavService,
    attendees: allEmails,
    organizerEmail,
    date: eventStart,
    enabled: allEmails.length > 0,
  });

  const handleDateChange = (date: Date) => {
    const newStart = new Date(eventStart);
    newStart.setFullYear(date.getFullYear(), date.getMonth(), date.getDate());
    const newEnd = new Date(eventEnd);
    newEnd.setFullYear(date.getFullYear(), date.getMonth(), date.getDate());
    onStartChange(formatDateTimeLocal(newStart));
    onEndChange(formatDateTimeLocal(newEnd));
  };

  const handleTimeSelect = (start: Date, end: Date) => {
    onStartChange(formatDateTimeLocal(start));
    onEndChange(formatDateTimeLocal(end));
  };

  return (
    <SectionRow
      icon="event_available"
      label={t("scheduling.findATime")}
      alwaysOpen={alwaysOpen}
      iconAlign="flex-start"
    >
      <FreeBusyTimeline
        date={eventStart}
        attendees={data}
        displayNames={resourceNames}
        eventStart={eventStart}
        eventEnd={eventEnd}
        isLoading={isLoading}
        onDateChange={handleDateChange}
        onTimeSelect={handleTimeSelect}
      />
    </SectionRow>
  );
};
