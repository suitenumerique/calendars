import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";

import { useIsMobile } from "@/hooks/useIsMobile";
import { useCalendarLocale } from "../../hooks/useCalendarLocale";
import { SectionRow } from "./event-modal-sections/SectionRow";
import type { ReadOnlyEventModalProps } from "./types";

export const ReadOnlyEventModal = ({
  isOpen,
  event,
  calendarUrl,
  calendars,
  onClose,
}: ReadOnlyEventModalProps) => {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const { intlLocale } = useCalendarLocale();

  const calendarName = useMemo(() => {
    const cal = calendars.find((c) => c.url === calendarUrl);
    return cal?.displayName || calendarUrl;
  }, [calendars, calendarUrl]);

  const formattedDateTime = useMemo(() => {
    if (!event?.start?.date) return "";

    const start =
      event.start.date instanceof Date
        ? event.start.date
        : new Date(event.start.date);

    const isAllDay = event.start.type === "DATE";

    if (isAllDay) {
      const dateFormatter = new Intl.DateTimeFormat(intlLocale, {
        timeZone: "UTC",
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      });

      if (event.end?.date) {
        const end =
          event.end.date instanceof Date
            ? event.end.date
            : new Date(event.end.date);
        const endMinusOne = new Date(end.getTime() - 86400000);
        if (endMinusOne.getTime() <= start.getTime()) {
          return dateFormatter.format(start);
        }
        return `${dateFormatter.format(start)} — ${dateFormatter.format(endMinusOne)}`;
      }
      return dateFormatter.format(start);
    }

    // Dates from the adapter use "fake UTC" — UTC components hold the
    // local-timezone time. We must format with timeZone: "UTC" so the
    // formatter reads those UTC components as-is.
    const dateTimeFormatter = new Intl.DateTimeFormat(intlLocale, {
      timeZone: "UTC",
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

    if (event.end?.date) {
      const end =
        event.end.date instanceof Date
          ? event.end.date
          : new Date(event.end.date);

      const sameDay =
        start.getUTCFullYear() === end.getUTCFullYear() &&
        start.getUTCMonth() === end.getUTCMonth() &&
        start.getUTCDate() === end.getUTCDate();

      if (sameDay) {
        const timeFormatter = new Intl.DateTimeFormat(intlLocale, {
          timeZone: "UTC",
          hour: "2-digit",
          minute: "2-digit",
        });
        return `${dateTimeFormatter.format(start)} — ${timeFormatter.format(end)}`;
      }
      return `${dateTimeFormatter.format(start)} — ${dateTimeFormatter.format(end)}`;
    }

    return dateTimeFormatter.format(start);
  }, [event, intlLocale]);

  const organizer = event?.organizer;
  const attendees = event?.attendees;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={isMobile ? ModalSize.FULL : ModalSize.MEDIUM}
      title={t("calendar.event.viewTitle")}
      rightActions={
        <Button color="neutral" onClick={onClose}>
          {t("common.close")}
        </Button>
      }
    >
      <div className="event-modal__content">
        {event?.summary && (
          <SectionRow icon="edit" label={t("calendar.event.title")} alwaysOpen>
            <span className="readonly-event__title">{event.summary}</span>
          </SectionRow>
        )}

        <SectionRow
          icon="event"
          label={t("calendar.event.calendar")}
          alwaysOpen
        >
          <span className="readonly-event__text">{calendarName}</span>
        </SectionRow>

        {formattedDateTime && (
          <SectionRow
            icon="schedule"
            label={t("calendar.event.date")}
            alwaysOpen
          >
            <span className="readonly-event__text">{formattedDateTime}</span>
          </SectionRow>
        )}

        {event?.location && (
          <SectionRow
            icon="place"
            label={t("calendar.event.location")}
            alwaysOpen
          >
            <span className="readonly-event__text">{event.location}</span>
          </SectionRow>
        )}

        {event?.description && (
          <SectionRow
            icon="notes"
            label={t("calendar.event.description")}
            alwaysOpen
            iconAlign="flex-start"
          >
            <p className="readonly-event__description">{event.description}</p>
          </SectionRow>
        )}

        {organizer && (
          <SectionRow
            icon="person"
            label={t("calendar.event.organizer")}
            alwaysOpen
          >
            <span className="readonly-event__text">
              {organizer.name || organizer.email}
            </span>
          </SectionRow>
        )}

        {attendees && attendees.length > 0 && (
          <SectionRow
            icon="group"
            label={t("calendar.event.attendees")}
            alwaysOpen
            iconAlign="flex-start"
          >
            <ul className="readonly-event__attendee-list">
              {attendees.map((att, index) => (
                <li key={att.email || att.name || index} className="readonly-event__attendee">
                  <span>{att.name || att.email}</span>
                  {att.partstat && att.partstat !== "NEEDS-ACTION" && (
                    <span className="readonly-event__attendee-status">
                      {" "}
                      ({att.partstat.toLowerCase()})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </SectionRow>
        )}
      </div>
    </Modal>
  );
};
