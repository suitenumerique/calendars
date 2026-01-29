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
 * - Custom toolbar with navigation and view selection
 *
 * Next.js consideration: This component must be client-side only
 * due to DOM manipulation. Use dynamic import with ssr: false if needed.
 */

import "@event-calendar/core/index.css";

import { useCallback, useEffect, useRef, useState } from "react";

import { useCalendarContext } from "../../contexts/CalendarContext";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";

import { EventModal } from "./EventModal";
import { SchedulerToolbar } from "./SchedulerToolbar";
import type { SchedulerProps, EventModalState } from "./types";
import { useSchedulerHandlers } from "./hooks/useSchedulerHandlers";
import {
  useSchedulerInit,
  useSchedulingCapabilitiesCheck,
} from "./hooks/useSchedulerInit";

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
  const calendarRef = contextCalendarRef;
  const [calendarUrl, setCalendarUrl] = useState(defaultCalendarUrl || "");

  // Toolbar state
  const [currentView, setCurrentView] = useState("timeGridWeek");
  const [viewTitle, setViewTitle] = useState("");

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
    calendarRef,
    calendarUrl,
    modalState,
    setModalState,
  });

  // Callback to update toolbar state when calendar dates/view changes
  const handleDatesSet = useCallback(
    (info: {
      start: Date;
      end: Date;
      view?: { type: string; title: string };
    }) => {
      // Update current date for MiniCalendar sync
      const midTime = (info.start.getTime() + info.end.getTime()) / 2;
      setCurrentDate(new Date(midTime));

      // Update toolbar state
      if (calendarRef.current) {
        const view = calendarRef.current.getView();
        if (view) {
          setCurrentView(view.type);
          setViewTitle(view.title);
        }
      }
    },
    [setCurrentDate, calendarRef],
  );

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
    setCurrentDate: handleDatesSet,
    handleEventClick: handleEventClick as (info: unknown) => void,
    handleEventDrop: handleEventDrop as unknown as (info: unknown) => void,
    handleEventResize: handleEventResize as unknown as (info: unknown) => void,
    handleDateClick: handleDateClick as (info: unknown) => void,
    handleSelect: handleSelect as (info: unknown) => void,
  });

  // Update toolbar title on initial render
  useEffect(() => {
    if (calendarRef.current) {
      const view = calendarRef.current.getView();
      if (view) {
        setCurrentView(view.type);
        setViewTitle(view.title);
      }
    }
  }, [isConnected]);

  // Update eventFilter when visible calendars change
  useEffect(() => {
    if (calendarRef.current) {
      // The refs are already updated (synchronously during render)
      // Now trigger a re-evaluation of eventFilter by calling refetchEvents
      calendarRef.current.refetchEvents();
    }
  }, [visibleCalendarUrls, davCalendars]);

  const handleViewChange = useCallback((view: string) => {
    setCurrentView(view);
  }, []);

  return (
    <div className="scheduler">
      <SchedulerToolbar
        calendarRef={calendarRef}
        currentView={currentView}
        viewTitle={viewTitle}
        onViewChange={handleViewChange}
      />

      <div
        ref={containerRef}
        id="event-calendar"
        className="scheduler__calendar"
        style={{ height: "calc(100vh - 52px - 90px)" }}
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
    </div>
  );
};

export default Scheduler;
