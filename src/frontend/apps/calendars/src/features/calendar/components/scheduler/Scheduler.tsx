/**
 * Scheduler component using EventCalendar (vkurko/calendar).
 * Renders a CalDAV-connected calendar view with full interactivity.
 *
 * Features:
 * - Drag & drop events (eventDrop)
 * - Resize events (eventResize)
 * - Click to edit (eventClick)
 * - Click to create (dateClick)
 * - Select range to create (select)
 *
 * Next.js consideration: This component must be client-side only
 * due to DOM manipulation. Use dynamic import with ssr: false if needed.
 */

import "@event-calendar/core/index.css";

import { useEffect, useRef, useState } from "react";

import { useCalendarContext } from "../../contexts/CalendarContext";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import type { EventCalendarEvent } from "../../services/dav/types/event-calendar";

import { EventModal } from "./EventModal";
import type { SchedulerProps, EventModalState } from "./types";
import { useSchedulerHandlers } from "./hooks/useSchedulerHandlers";
import {
  useSchedulerInit,
  useSchedulingCapabilitiesCheck,
} from "./hooks/useSchedulerInit";

type ECEvent = EventCalendarEvent;

// Calendar API interface
interface CalendarApi {
  updateEvent: (event: ECEvent) => void;
  addEvent: (event: ECEvent) => void;
  unselect: () => void;
  refetchEvents: () => void;
  $destroy?: () => void;
}

export const Scheduler = ({ defaultCalendarUrl }: SchedulerProps) => {
  const {
    caldavService,
    adapter,
    davCalendars,
    visibleCalendarUrls,
    isConnected,
    calendarRef: contextCalendarRef,
    setCurrentDate,
  } = useCalendarContext();

  const containerRef = useRef<HTMLDivElement>(null);
  const calendarRef = contextCalendarRef as React.MutableRefObject<CalendarApi | null>;
  const [calendarUrl, setCalendarUrl] = useState(defaultCalendarUrl || "");

  // Modal state
  const [modalState, setModalState] = useState<EventModalState>({
    isOpen: false,
    mode: "create",
    event: null,
    calendarUrl: "",
  });

  // Keep refs to visibleCalendarUrls and davCalendars for use in eventFilter/eventSources
  const visibleCalendarUrlsRef = useRef(visibleCalendarUrls);
  visibleCalendarUrlsRef.current = visibleCalendarUrls;

  const davCalendarsRef = useRef<CalDavCalendar[]>(davCalendars);
  davCalendarsRef.current = davCalendars;

  // Initialize calendar URL from context
  useEffect(() => {
    if (davCalendars.length > 0 && !calendarUrl) {
      const firstCalendar = davCalendars[0];
      setCalendarUrl(defaultCalendarUrl || firstCalendar.url);
    }
  }, [davCalendars, defaultCalendarUrl, calendarUrl]);

  // Check scheduling capabilities on mount
  useSchedulingCapabilitiesCheck(isConnected, caldavService);

  // Initialize event handlers
  const {
    handleEventDrop,
    handleEventResize,
    handleEventClick,
    handleDateClick,
    handleSelect,
    handleModalSave,
    handleModalDelete,
    handleModalClose,
    handleRespondToInvitation,
  } = useSchedulerHandlers({
    adapter,
    caldavService,
    davCalendarsRef,
    calendarRef,
    calendarUrl,
    modalState,
    setModalState,
  });

  // Initialize calendar
  // Cast handlers to bypass library type differences between specific event types and unknown
  useSchedulerInit({
    containerRef,
    calendarRef,
    isConnected,
    calendarUrl,
    caldavService,
    adapter,
    visibleCalendarUrlsRef,
    davCalendarsRef,
    setCurrentDate,
    handleEventClick: handleEventClick as (info: unknown) => void,
    handleEventDrop: handleEventDrop as unknown as (info: unknown) => void,
    handleEventResize: handleEventResize as unknown as (info: unknown) => void,
    handleDateClick: handleDateClick as (info: unknown) => void,
    handleSelect: handleSelect as (info: unknown) => void,
  });

  // Update eventFilter when visible calendars change
  useEffect(() => {
    if (calendarRef.current) {
      // The refs are already updated (synchronously during render)
      // Now trigger a re-evaluation of eventFilter by calling refetchEvents
      calendarRef.current.refetchEvents();
    }
  }, [visibleCalendarUrls, davCalendars]);

  return (
    <>
      <div
        ref={containerRef}
        id="event-calendar"
        style={{ height: "calc(100vh - 100px)" }}
      />

      <EventModal
        isOpen={modalState.isOpen}
        mode={modalState.mode}
        event={modalState.event}
        calendarUrl={modalState.calendarUrl}
        calendars={davCalendars}
        adapter={adapter}
        onSave={handleModalSave}
        onDelete={modalState.mode === "edit" ? handleModalDelete : undefined}
        onRespondToInvitation={handleRespondToInvitation}
        onClose={handleModalClose}
      />
    </>
  );
};

export default Scheduler;
