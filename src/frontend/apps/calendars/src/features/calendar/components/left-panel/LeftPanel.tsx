/**
 * LeftPanel component - Calendar sidebar with mini calendar and calendar list.
 */

import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button, useModal } from "@gouvfr-lasuite/cunningham-react";
import { IcsEvent } from "ts-ics";

import { CalendarList } from "../calendar-list";
import { MiniCalendar } from "./MiniCalendar";
import { EventModal } from "../scheduler/EventModal";
import { useCalendarContext } from "../../contexts";

const BROWSER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

/**
 * Get rounded start and end times for a new event.
 * Rounds down to the current hour, end is 1 hour later.
 * Example: 14:30 -> start: 14:00, end: 15:00
 */
const getDefaultEventTimes = () => {
  const now = new Date();
  const start = new Date(now);
  start.setMinutes(0, 0, 0);

  const end = new Date(start);
  end.setHours(end.getHours() + 1);

  return { start, end };
};

export const LeftPanel = () => {
  const { t } = useTranslation();
  const modal = useModal();

  const {
    selectedDate,
    setSelectedDate,
    davCalendars,
    caldavService,
    adapter,
    calendarRef,
  } = useCalendarContext();

  // Get default calendar URL
  const defaultCalendarUrl = davCalendars[0]?.url || "";

  // Create default event with rounded times
  const defaultEvent = useMemo(() => {
    const { start, end } = getDefaultEventTimes();

    // Create "fake UTC" dates for the adapter
    const fakeUtcStart = new Date(
      Date.UTC(
        start.getFullYear(),
        start.getMonth(),
        start.getDate(),
        start.getHours(),
        start.getMinutes(),
        0
      )
    );
    const fakeUtcEnd = new Date(
      Date.UTC(
        end.getFullYear(),
        end.getMonth(),
        end.getDate(),
        end.getHours(),
        end.getMinutes(),
        0
      )
    );

    return {
      start: {
        date: fakeUtcStart,
        type: "DATE-TIME" as const,
        local: {
          date: fakeUtcStart,
          timezone: BROWSER_TIMEZONE,
          tzoffset: adapter.getTimezoneOffset(start, BROWSER_TIMEZONE),
        },
      },
      end: {
        date: fakeUtcEnd,
        type: "DATE-TIME" as const,
        local: {
          date: fakeUtcEnd,
          timezone: BROWSER_TIMEZONE,
          tzoffset: adapter.getTimezoneOffset(end, BROWSER_TIMEZONE),
        },
      },
    };
  }, [adapter]);

  // Handle save event
  const handleSave = useCallback(
    async (event: IcsEvent, calendarUrl: string) => {
      const result = await caldavService.createEvent({
        calendarUrl,
        event,
      });

      if (!result.success) {
        throw new Error(result.error || "Failed to create event");
      }

      // Refresh the calendar view
      if (calendarRef.current) {
        calendarRef.current.refetchEvents();
      }
    },
    [caldavService, calendarRef]
  );

  const handleClose = useCallback(() => {
    modal.close();
  }, [modal]);

  return (
    <>
      <div className="calendar-left-panel">
        <div className="calendar-left-panel__create">
          <Button
            onClick={modal.open}
            icon={<span className="material-icons">add</span>}
          >
            {t("calendar.leftPanel.newEvent")}
          </Button>
        </div>

        <MiniCalendar
          selectedDate={selectedDate}
          onDateSelect={setSelectedDate}
        />

        <div className="calendar-left-panel__divider" />

        <CalendarList />
      </div>

      {modal.isOpen && (
        <EventModal
          isOpen={modal.isOpen}
          mode="create"
          event={defaultEvent}
          calendarUrl={defaultCalendarUrl}
          calendars={davCalendars}
          adapter={adapter}
          onSave={handleSave}
          onClose={handleClose}
        />
      )}
    </>
  );
};
