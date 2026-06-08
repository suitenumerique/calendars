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
 * - Mobile-optimized views (1 day, 2 days, list)
 */

import "@event-calendar/core/index.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { MobileToolbar } from "./mobile/MobileToolbar";
import { WeekDayBar } from "./mobile/WeekDayBar";
import { FloatingActionButton } from "./mobile/FloatingActionButton";
import { MobileListView } from "./mobile/MobileListView";
import { useCalendarContext } from "../../contexts/CalendarContext";
import { useCalendarLocale } from "../../hooks/useCalendarLocale";
import { useIsMobile } from "@/hooks/useIsMobile";
import { EventModal } from "./EventModal";
import { RecurringEditModal } from "./RecurringEditModal";
import { SchedulerToolbar } from "./SchedulerToolbar";
import { useSchedulerHandlers } from "./hooks/useSchedulerHandlers";
import { useSchedulerInit, useSchedulingCapabilitiesCheck } from "./hooks/useSchedulerInit";
import { useMobileNavigation } from "./hooks/useMobileNavigation";

import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import type { CalDavExtendedProps } from "../../services/dav/EventCalendarAdapter";
import type { EventCalendarEvent } from "../../services/dav/types/event-calendar";

import type { SchedulerProps, EventModalState, MobileListEvent } from "./types";

const BROWSER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

export const Scheduler = ({ defaultCalendarUrl }: SchedulerProps) => {
  const {
    caldavService,
    adapter,
    davCalendars,
    orderedCalendars,
    visibleCalendarUrls,
    isConnected,
    calendarRef: contextCalendarRef,
    currentDate,
    setCurrentDate,
  } = useCalendarContext();

  const isMobile = useIsMobile();
  const { firstDayOfWeek, intlLocale } = useCalendarLocale();

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

  // Mirror currentDate into a ref so useSchedulerInit can restore the
  // viewport on locale/firstDayOfWeek-triggered recreates without
  // listing currentDate in its dependency array (which would re-create
  // on every navigation tick).
  const currentDateRef = useRef<Date>(currentDate);
  currentDateRef.current = currentDate;

  // Initialize calendar URL from context
  useEffect(() => {
    if (orderedCalendars.length > 0 && !calendarUrl) {
      // Default to the first calendar in the displayed order (top of the
      // sidebar), not the raw server order.
      const firstCalendar = orderedCalendars[0];
      setCalendarUrl(defaultCalendarUrl || firstCalendar.url);
    }
  }, [orderedCalendars, defaultCalendarUrl, calendarUrl]);

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
    pendingRecurringAction,
    handlePendingRecurringConfirm,
    handlePendingRecurringCancel,
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
    (info: { start: Date; end: Date; view?: { type: string; title: string } }) => {
      // Update current date for MiniCalendar sync
      // Use start for short views (day, 2-day) to avoid mid-point drift,
      // use midpoint for longer views (week, month) for better centering
      const durationMs = info.end.getTime() - info.start.getTime();
      const threeDaysMs = 3 * 24 * 60 * 60 * 1000;
      const syncDate =
        durationMs <= threeDaysMs
          ? info.start
          : new Date((info.start.getTime() + info.end.getTime()) / 2);
      setCurrentDate(syncDate);

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

  // Counter incremented each time the calendar finishes loading events
  const [eventsLoadedCounter, setEventsLoadedCounter] = useState(0);
  const handleEventsLoaded = useCallback(() => {
    setEventsLoadedCounter((c) => c + 1);
  }, []);

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
    initialView: isMobile ? "timeGridDay" : "timeGridWeek",
    currentDateRef,
    setCurrentDate: handleDatesSet,
    handleEventClick: handleEventClick as (info: unknown) => void,
    handleEventDrop: handleEventDrop as unknown as (info: unknown) => void,
    handleEventResize: handleEventResize as unknown as (info: unknown) => void,
    handleDateClick: handleDateClick as (info: unknown) => void,
    handleSelect: handleSelect as (info: unknown) => void,
    onEventsLoaded: handleEventsLoaded,
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
      calendarRef.current.refetchEvents();
    }
  }, [visibleCalendarUrls, davCalendars]);

  const handleViewChange = useCallback(
    (view: string) => {
      calendarRef.current?.setOption("view", view);
      setCurrentView(view);
    },
    [calendarRef],
  );

  // Auto-switch view when crossing mobile/desktop breakpoint
  const prevIsMobileRef = useRef(isMobile);
  useEffect(() => {
    if (prevIsMobileRef.current === isMobile) return;
    prevIsMobileRef.current = isMobile;
    const targetView = isMobile ? "timeGridDay" : "timeGridWeek";
    handleViewChange(targetView);
  }, [isMobile, handleViewChange]);

  // Mobile list view events (extracted from ref via effect to avoid ref access during render)
  // Re-use the same empty-array reference for the "no list view" case
  // so setListEvents([]) doesn't churn the state with a fresh reference
  // on every render — that was a contributor to the "Maximum update
  // depth exceeded" warning observed when the event grid re-rendered
  // immediately after a save.
  const EMPTY_LIST = useRef<MobileListEvent[]>([]).current;
  const [listEvents, setListEvents] = useState<MobileListEvent[]>(EMPTY_LIST);
  const isListView = isMobile && currentView === "listWeek";
  const currentDateMs = currentDate.getTime();

  useEffect(() => {
    if (!isListView || !calendarRef.current) {
      setListEvents(EMPTY_LIST);
      return;
    }

    const extractTitle = (
      title: string | { html: string } | { domNodes: Node[] } | undefined,
    ): string => {
      if (!title) return "";
      if (typeof title === "string") return title;
      if ("html" in title) {
        const div = document.createElement("div");
        div.innerHTML = title.html;
        return div.textContent || "";
      }
      return "";
    };

    const rawEvents = calendarRef.current.getEvents();
    const parsed: MobileListEvent[] = rawEvents.map((e) => ({
      id: String(e.id),
      title: extractTitle(e.title),
      start: new Date(e.start),
      end: e.end ? new Date(e.end) : new Date(e.start),
      allDay: e.allDay ?? false,
      backgroundColor: e.backgroundColor || "#2563eb",
      extendedProps: e.extendedProps ?? {},
    }));
    setListEvents(parsed);
    // EMPTY_LIST is a stable ref-created sentinel — listing it here would
    // never re-fire the effect, so it's intentionally omitted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isListView, currentDateMs, visibleCalendarUrls, eventsLoadedCounter]);

  // Mobile navigation
  const { weekDays, handleWeekPrev, handleWeekNext, handleDayClick, handleTodayClick } =
    useMobileNavigation({
      currentDate,
      firstDayOfWeek,
      calendarRef,
    });

  // FAB click: open create modal with current date/time
  const handleFabClick = useCallback(() => {
    const now = new Date();
    const startDate = new Date(currentDate);
    startDate.setHours(now.getHours(), 0, 0, 0);
    const endDate = new Date(startDate);
    endDate.setHours(startDate.getHours() + 1);

    const defaultUrl = calendarUrl || orderedCalendars[0]?.url || "";

    setModalState({
      isOpen: true,
      mode: "create",
      event: {
        uid: crypto.randomUUID(),
        stamp: { date: new Date() },
        start: { date: startDate, type: "DATE-TIME" },
        end: { date: endDate, type: "DATE-TIME" },
      },
      calendarUrl: defaultUrl,
    });
  }, [currentDate, calendarUrl, orderedCalendars]);

  // Mobile list view event click
  const handleMobileEventClick = useCallback(
    (eventId: string, extendedProps: Record<string, unknown>) => {
      const events = calendarRef.current?.getEvents() ?? [];
      const event = events.find((e) => String(e.id) === eventId);
      if (!event) return;

      const extProps = extendedProps as CalDavExtendedProps;
      const icsEvent = adapter.toIcsEvent(event as EventCalendarEvent, {
        defaultTimezone: extProps?.timezone || BROWSER_TIMEZONE,
      });

      setModalState({
        isOpen: true,
        mode: "edit",
        event: icsEvent,
        calendarUrl: extProps?.calendarUrl || calendarUrl,
        eventUrl: extProps?.eventUrl,
        etag: extProps?.etag,
      });
    },
    [adapter, calendarUrl, calendarRef],
  );

  // Mobile multi-day views use the library's native per-column headers
  // (aligned with each day column, like desktop). The WeekDayBar — which
  // shows a 7-day strip with the visible window highlighted — is kept for
  // the single-day grid (where it doubles as a day picker) and for the
  // list view (where it anchors the current day).
  const showWeekDayBar = isMobile && (currentView === "timeGridDay" || currentView === "listWeek");

  return (
    <div className="scheduler" data-view={currentView}>
      {isMobile ? (
        <>
          <MobileToolbar
            calendarRef={calendarRef}
            currentView={currentView}
            currentDate={currentDate}
            onViewChange={handleViewChange}
            onWeekPrev={handleWeekPrev}
            onWeekNext={handleWeekNext}
            onTodayClick={handleTodayClick}
          />
          {showWeekDayBar && (
            <WeekDayBar
              currentDate={currentDate}
              currentView={currentView}
              intlLocale={intlLocale}
              weekDays={weekDays}
              onDayClick={handleDayClick}
            />
          )}
        </>
      ) : (
        <SchedulerToolbar
          calendarRef={calendarRef}
          currentView={currentView}
          viewTitle={viewTitle}
          onViewChange={handleViewChange}
        />
      )}

      {isListView && (
        <MobileListView
          weekDays={weekDays}
          events={listEvents}
          intlLocale={intlLocale}
          onEventClick={handleMobileEventClick}
        />
      )}
      <div
        ref={containerRef}
        id="event-calendar"
        className="scheduler__calendar"
        style={{
          display: isListView ? "none" : undefined,
        }}
      />

      {isMobile && <FloatingActionButton onClick={handleFabClick} />}

      <EventModal
        key={`${modalState.mode}-${modalState.event?.uid ?? "none"}-${
          modalState.event?.recurrenceId?.value?.date instanceof Date
            ? modalState.event.recurrenceId.value.date.getTime()
            : ""
        }`}
        isOpen={modalState.isOpen}
        mode={modalState.mode}
        event={modalState.event}
        calendarUrl={modalState.calendarUrl}
        calendars={orderedCalendars}
        adapter={adapter}
        onSave={handleModalSave}
        onDelete={modalState.mode === "edit" ? handleModalDelete : undefined}
        onRespondToInvitation={handleRespondToInvitation}
        onClose={handleModalClose}
      />

      <RecurringEditModal
        isOpen={!!pendingRecurringAction}
        onConfirm={handlePendingRecurringConfirm}
        onCancel={handlePendingRecurringCancel}
      />
    </div>
  );
};

export default Scheduler;
