/**
 * useSchedulerInit hook.
 * Handles calendar initialization and configuration.
 */

import { useEffect, useRef, MutableRefObject } from "react";
import { useTranslation } from "react-i18next";
import {
  createCalendar,
  TimeGrid,
  DayGrid,
  List,
  Interaction,
} from "@event-calendar/core";

import { useCalendarLocale } from "../../../hooks/useCalendarLocale";
import type { EventCalendarAdapter, CalDavExtendedProps } from "../../../services/dav/EventCalendarAdapter";
import type { CalDavService } from "../../../services/dav/CalDavService";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";
import type { EventCalendarEvent, EventCalendarFetchInfo } from "../../../services/dav/types/event-calendar";
import type { CalendarApi } from "../types";

type ECEvent = EventCalendarEvent;

interface UseSchedulerInitProps {
  containerRef: MutableRefObject<HTMLDivElement | null>;
  calendarRef: MutableRefObject<CalendarApi | null>;
  isConnected: boolean;
  calendarUrl: string;
  caldavService: CalDavService;
  adapter: EventCalendarAdapter;
  visibleCalendarUrlsRef: MutableRefObject<Set<string>>;
  davCalendarsRef: MutableRefObject<CalDavCalendar[]>;
  setCurrentDate: (info: { start: Date; end: Date }) => void;
  handleEventClick: (info: unknown) => void;
  handleEventDrop: (info: unknown) => void;
  handleEventResize: (info: unknown) => void;
  handleDateClick: (info: unknown) => void;
  handleSelect: (info: unknown) => void;
}

// Helper to get current time as HH:MM string
const getCurrentTimeString = (): string => {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
};

export const useSchedulerInit = ({
  containerRef,
  calendarRef,
  isConnected,
  calendarUrl,
  caldavService,
  adapter,
  visibleCalendarUrlsRef,
  davCalendarsRef,
  setCurrentDate,
  handleEventClick,
  handleEventDrop,
  handleEventResize,
  handleDateClick,
  handleSelect,
}: UseSchedulerInitProps) => {
  const { t, i18n } = useTranslation();
  const { calendarLocale, firstDayOfWeek, formatDayHeader } = useCalendarLocale();

  // Capture initial scroll time only once on first render
  const initialScrollTimeRef = useRef<string>(getCurrentTimeString());

  // Store event handlers in refs for stable references (advanced-event-handler-refs pattern)
  // This prevents calendar recreation when handlers change (e.g., when modalState changes)
  const handlersRef = useRef({
    handleEventClick,
    handleEventDrop,
    handleEventResize,
    handleDateClick,
    handleSelect,
    setCurrentDate,
  });

  // Update refs when handlers change (no effect dependencies = no calendar recreation)
  useEffect(() => {
    handlersRef.current = {
      handleEventClick,
      handleEventDrop,
      handleEventResize,
      handleDateClick,
      handleSelect,
      setCurrentDate,
    };
  });

  useEffect(() => {
    if (!containerRef.current || calendarRef.current || !isConnected) return;

    const ec = createCalendar(
      containerRef.current,
      [TimeGrid, DayGrid, List, Interaction],
      {
        // View configuration
        view: "timeGridWeek",
        // Native toolbar disabled - using custom React toolbar (SchedulerToolbar)
        headerToolbar: false,

        // Locale & time settings
        locale: calendarLocale,
        firstDay: firstDayOfWeek,
        slotDuration: "00:30",
        scrollTime: initialScrollTimeRef.current,
        displayEventEnd: true,

        // Interactive features
        editable: true,
        selectable: true,
        dragScroll: true,
        eventStartEditable: true,
        eventDurationEditable: true,
        selectMinDistance: 5,
        eventDragMinDistance: 5,
        selectBackgroundColor: '#ffcdd2', // Light red color for selection

        // Event handlers - ALL INTERACTIONS
        // Use ref wrappers for stable references (prevents calendar recreation on handler changes)
        eventClick: (info: unknown) => handlersRef.current.handleEventClick(info),
        eventDrop: (info: unknown) => handlersRef.current.handleEventDrop(info),
        eventResize: (info: unknown) => handlersRef.current.handleEventResize(info),
        dateClick: (info: unknown) => handlersRef.current.handleDateClick(info),
        select: (info: unknown) => handlersRef.current.handleSelect(info),

        // Sync current date with MiniCalendar when navigating
        datesSet: (info: { start: Date; end: Date }) => {
          handlersRef.current.setCurrentDate(info);
        },

        // Event display
        dayMaxEvents: true,
        nowIndicator: true,

        // Date formatting (locale-aware)
        dayHeaderFormat: formatDayHeader,

        eventFilter: (info: { event: ECEvent; view: unknown }) => {
          // Filter events based on visible calendars using the ref
          const extProps = info.event.extendedProps as CalDavExtendedProps | undefined;
          const eventCalendarUrl = extProps?.calendarUrl;
          if (!eventCalendarUrl) return true;
          return visibleCalendarUrlsRef.current.has(eventCalendarUrl);
        },

        // Event sources - fetch from ALL CalDAV calendars (filtering done by eventFilter)
        eventSources: [
          {
            events: async (fetchInfo: EventCalendarFetchInfo) => {
              const calendars = davCalendarsRef.current;
              if (calendars.length === 0) return [];

              try {
                // Fetch events from ALL calendars in parallel
                const allEventsPromises = calendars.map(async (calendar) => {
                  const timeRange = {
                    start: fetchInfo.start,
                    end: fetchInfo.end,
                  };

                  // Fetch source events and expanded instances in parallel
                  const [sourceEventsResult, expandedEventsResult] = await Promise.all([
                    caldavService.fetchEvents(calendar.url, { timeRange, expand: false }),
                    caldavService.fetchEvents(calendar.url, { timeRange, expand: true }),
                  ]);

                  if (!expandedEventsResult.success || !expandedEventsResult.data) {
                    console.error(
                      `Failed to fetch events from ${calendar.url}:`,
                      expandedEventsResult.error
                    );
                    return [];
                  }

                  // Build a map of source recurrence rules by UID
                  const sourceRulesByUid = new Map<string, unknown>();
                  if (sourceEventsResult.success && sourceEventsResult.data) {
                    for (const sourceEvent of sourceEventsResult.data) {
                      const icsEvents = sourceEvent.data.events ?? [];
                      for (const icsEvent of icsEvents) {
                        if (icsEvent.recurrenceRule && !icsEvent.recurrenceId) {
                          sourceRulesByUid.set(icsEvent.uid, icsEvent.recurrenceRule);
                        }
                      }
                    }
                  }

                  // Enrich expanded events with recurrence rules from sources
                  const enrichedExpandedData = expandedEventsResult.data.map(
                    (event) => {
                      const enrichedEvents = event.data.events?.map((icsEvent) => {
                        // If this is an instance without recurrenceRule, add it from source
                        if (icsEvent.recurrenceId && !icsEvent.recurrenceRule) {
                          const sourceRule = sourceRulesByUid.get(icsEvent.uid);
                          if (sourceRule) {
                            return { ...icsEvent, recurrenceRule: sourceRule };
                          }
                        }
                        return icsEvent;
                      });

                      return {
                        ...event,
                        data: {
                          ...event.data,
                          events: enrichedEvents,
                        },
                      };
                    }
                  );

                  const calendarColors = adapter.createCalendarColorMap(calendars);
                  // Type assertion needed due to the enrichment process
                  return adapter.toEventCalendarEvents(
                    enrichedExpandedData as typeof expandedEventsResult.data,
                    { calendarColors }
                  );
                });

                const allEventsArrays = await Promise.all(allEventsPromises);
                return allEventsArrays.flat() as ECEvent[];
              } catch (error) {
                console.error("Error fetching events:", error);
                return [];
              }
            },
          },
        ],

        // Loading state is handled internally by the calendar
      }
    );

    calendarRef.current = ec as unknown as CalendarApi;

    return () => {
      // @event-calendar/core is Svelte-based and uses $destroy
      // Always call $destroy before clearing the container to avoid memory leaks
      if (calendarRef.current) {
        const calendar = calendarRef.current as CalendarApi;
        if (typeof calendar.$destroy === 'function') {
          calendar.$destroy();
        }
        calendarRef.current = null;
      }
      // Clear the container only after calendar is destroyed
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
    // Note: refs (containerRef, calendarRef, visibleCalendarUrlsRef, davCalendarsRef, initialScrollTimeRef, handlersRef)
    // are excluded from dependencies as they are stable references that don't trigger re-renders.
    // Event handlers are accessed via handlersRef to prevent calendar recreation on handler changes.
  }, [
    isConnected,
    calendarUrl,
    calendarLocale,
    firstDayOfWeek,
    formatDayHeader,
    caldavService,
    adapter,
    t,
    i18n.language,
  ]);
};

/**
 * Hook to check scheduling capabilities on mount.
 * Silently verifies CalDAV scheduling support without debug output.
 */
export const useSchedulingCapabilitiesCheck = (
  isConnected: boolean,
  caldavService: CalDavService
) => {
  const hasCheckedRef = useRef(false);

  useEffect(() => {
    if (!isConnected || hasCheckedRef.current) return;

    hasCheckedRef.current = true;

    // Silently check scheduling capabilities
    // Debug logging removed for production
    caldavService.getSchedulingCapabilities();
  }, [isConnected, caldavService]);
};
