/**
 * useSchedulerInit hook.
 * Handles calendar initialization and configuration.
 */

import { useEffect, useRef } from "react";
import type { MutableRefObject } from "react";
import { useTranslation } from "react-i18next";
import {
  createCalendar,
  destroyCalendar,
  TimeGrid,
  DayGrid,
  List,
  Interaction,
} from "@event-calendar/core";
import { useCalendarLocale } from "../../../hooks/useCalendarLocale";
import { createEventContent, type EventContentInfo } from "../utils/eventContent";

import type {
  EventCalendarAdapter,
  CalDavExtendedProps,
} from "../../../services/dav/EventCalendarAdapter";
import type { CalDavService } from "../../../services/dav/CalDavService";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";
import type {
  EventCalendarEvent,
  EventCalendarFetchInfo,
} from "../../../services/dav/types/event-calendar";
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
  initialView?: string;
  /**
   * Date the calendar should land on when (re)created. Stored in a ref
   * by the caller so locale / first-day changes that trigger a recreate
   * still restore the user's previous viewport instead of snapping
   * back to today.
   */
  currentDateRef?: MutableRefObject<Date>;
  setCurrentDate: (info: { start: Date; end: Date }) => void;
  handleEventClick: (info: unknown) => void;
  handleEventDrop: (info: unknown) => void;
  handleEventResize: (info: unknown) => void;
  handleDateClick: (info: unknown) => void;
  handleSelect: (info: unknown) => void;
  onEventsLoaded?: () => void;
}

// Helper to get current time as HH:MM string
const getCurrentTimeString = (): string => {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
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
  initialView = "timeGridWeek",
  currentDateRef,
  setCurrentDate,
  handleEventClick,
  handleEventDrop,
  handleEventResize,
  handleDateClick,
  handleSelect,
  onEventsLoaded,
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
    onEventsLoaded,
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
      onEventsLoaded,
    };
  });

  useEffect(() => {
    if (!containerRef.current || calendarRef.current || !isConnected) return;

    const ec = createCalendar(containerRef.current, [TimeGrid, DayGrid, List, Interaction], {
      // View configuration
      view: initialView,
      // Recreating the calendar (e.g. on locale / firstDayOfWeek
      // change) would otherwise snap back to today and yank the user
      // out of whatever week or month they were inspecting.
      ...(currentDateRef?.current ? { date: currentDateRef.current } : {}),
      // Native toolbar disabled - using custom React toolbar (SchedulerToolbar)
      headerToolbar: false,

      // Custom views
      views: {
        // Mon-Fri view: a normal week-grid with Sat/Sun hidden.
        // Using hiddenDays (rather than duration: { days: 5 }) gives a
        // week-aligned window — `next` always jumps a full week — and
        // keeps the Monday start regardless of the user's locale's
        // firstDay setting.
        timeGridWorkWeek: {
          type: "timeGridWeek",
          hiddenDays: [0, 6],
          firstDay: 1,
        },
      },

      // Locale & time settings
      locale: calendarLocale,
      firstDay: firstDayOfWeek,
      slotDuration: "00:30",
      scrollTime: initialScrollTimeRef.current,
      displayEventEnd: true,
      // @event-calendar/core renders the all-day lane label from the
      // ``allDayContent`` option (a string or content fn); when it's
      // undefined it falls back to the hardcoded English "all-day".
      // (NB: there is no ``allDayText`` option — an earlier attempt to
      // use that name was silently ignored.)
      allDayContent: t("calendar.event.allDay"),

      // Interactive features
      editable: true,
      selectable: true,
      dragScroll: true,
      eventStartEditable: true,
      eventDurationEditable: true,
      selectMinDistance: 5,
      eventDragMinDistance: 5,
      selectBackgroundColor: "#ffcdd2", // Light red color for selection

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

      // Custom event content — adapts layout to event duration
      eventContent: (info: EventContentInfo) => createEventContent(info),

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

      // Event sources - fetch only from visible calendars
      eventSources: [
        {
          events: async (fetchInfo: EventCalendarFetchInfo) => {
            const calendars = davCalendarsRef.current;
            if (calendars.length === 0) return [];

            // Only fetch events for calendars the user has toggled visible
            const visibleCalendars = calendars.filter((c) =>
              visibleCalendarUrlsRef.current.has(c.url),
            );
            if (visibleCalendars.length === 0) return [];

            try {
              const calendarColors = adapter.createCalendarColorMap(calendars);
              const timeRange = {
                start: fetchInfo.start,
                end: fetchInfo.end,
              };

              // Single expanded fetch per visible calendar
              const allEventsPromises = visibleCalendars.map(async (calendar) => {
                const result = await caldavService.fetchEvents(calendar.url, {
                  timeRange,
                  expand: true,
                });

                if (!result.success || !result.data) {
                  console.error(`Failed to fetch events from ${calendar.url}:`, result.error);
                  return [];
                }

                // Check if any expanded instances need recurrence rules
                const uidsNeedingRules = new Set<string>();
                for (const evt of result.data) {
                  for (const icsEvent of evt.data.events ?? []) {
                    if (icsEvent.recurrenceId && !icsEvent.recurrenceRule) {
                      uidsNeedingRules.add(icsEvent.uid);
                    }
                  }
                }

                // Only fetch source events if we actually need recurrence rules
                const sourceRulesByUid = new Map<string, unknown>();
                if (uidsNeedingRules.size > 0) {
                  const sourceResult = await caldavService.fetchEvents(calendar.url, {
                    timeRange,
                    expand: false,
                  });
                  if (sourceResult.success && sourceResult.data) {
                    for (const sourceEvent of sourceResult.data) {
                      for (const icsEvent of sourceEvent.data.events ?? []) {
                        if (icsEvent.recurrenceRule && !icsEvent.recurrenceId) {
                          sourceRulesByUid.set(icsEvent.uid, icsEvent.recurrenceRule);
                        }
                      }
                    }
                  }
                }

                // Enrich expanded events with recurrence rules from sources
                const enrichedData =
                  uidsNeedingRules.size > 0
                    ? result.data.map((event) => ({
                        ...event,
                        data: {
                          ...event.data,
                          events: event.data.events?.map((icsEvent) => {
                            if (icsEvent.recurrenceId && !icsEvent.recurrenceRule) {
                              const rule = sourceRulesByUid.get(icsEvent.uid);
                              if (rule)
                                return {
                                  ...icsEvent,
                                  recurrenceRule: rule,
                                };
                            }
                            return icsEvent;
                          }),
                        },
                      }))
                    : result.data;

                return adapter.toEventCalendarEvents(enrichedData as typeof result.data, {
                  calendarColors,
                });
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

      // Notify when events finish loading (used by mobile list view)
      loading: (isLoading: boolean) => {
        if (!isLoading) {
          handlersRef.current.onEventsLoaded?.();
        }
      },
    });

    calendarRef.current = ec as unknown as CalendarApi;

    return () => {
      if (calendarRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        destroyCalendar(calendarRef.current as any);
        calendarRef.current = null;
      }
      // Clear the container only after calendar is destroyed
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
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
  caldavService: CalDavService,
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
