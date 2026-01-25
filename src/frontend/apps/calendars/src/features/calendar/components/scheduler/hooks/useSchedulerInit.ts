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

type ECEvent = EventCalendarEvent;

// Calendar API interface
interface CalendarApi {
  updateEvent: (event: ECEvent) => void;
  addEvent: (event: ECEvent) => void;
  unselect: () => void;
  refetchEvents: () => void;
  $destroy?: () => void;
}

interface UseSchedulerInitProps {
  containerRef: MutableRefObject<HTMLDivElement | null>;
  calendarRef: MutableRefObject<CalendarApi | null>;
  isConnected: boolean;
  calendarUrl: string;
  caldavService: CalDavService;
  adapter: EventCalendarAdapter;
  visibleCalendarUrlsRef: MutableRefObject<Set<string>>;
  davCalendarsRef: MutableRefObject<CalDavCalendar[]>;
  setCurrentDate: (date: Date) => void;
  handleEventClick: (info: unknown) => void;
  handleEventDrop: (info: unknown) => void;
  handleEventResize: (info: unknown) => void;
  handleDateClick: (info: unknown) => void;
  handleSelect: (info: unknown) => void;
}

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

  useEffect(() => {
    if (!containerRef.current || calendarRef.current || !isConnected) return;

    const ec = createCalendar(
      containerRef.current,
      [TimeGrid, DayGrid, List, Interaction],
      {
        // View configuration
        view: "timeGridWeek",
        headerToolbar: {
          start: "prev,next today",
          center: "title",
          end: "dayGridMonth,timeGridWeek,timeGridDay,listWeek",
        },

        // Button text translations
        buttonText: {
          today: t('calendar.views.today'),
          dayGridMonth: t('calendar.views.month'),
          timeGridWeek: t('calendar.views.week'),
          timeGridDay: t('calendar.views.day'),
          listWeek: t('calendar.views.listWeek'),
        },

        // Locale & time settings
        locale: calendarLocale,
        firstDay: firstDayOfWeek,
        slotDuration: "00:30",
        scrollTime: "08:00",
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
        // Cast handlers to bypass library type differences (DomEvent vs MouseEvent)
        eventClick: handleEventClick as (info: unknown) => void,
        eventDrop: handleEventDrop as (info: unknown) => void,
        eventResize: handleEventResize as (info: unknown) => void,
        dateClick: handleDateClick as (info: unknown) => void,
        select: handleSelect as (info: unknown) => void,

        // Sync current date with MiniCalendar when navigating
        datesSet: (info: { start: Date; end: Date }) => {
          // Use the middle of the visible range as the "current" date
          const midTime = (info.start.getTime() + info.end.getTime()) / 2;
          setCurrentDate(new Date(midTime));
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
                  // Fetch source events (with recurrence rules) without expansion
                  const sourceEventsResult = await caldavService.fetchEvents(
                    calendar.url,
                    {
                      timeRange: {
                        start: fetchInfo.start,
                        end: fetchInfo.end,
                      },
                      expand: false,
                    }
                  );

                  // Fetch expanded instances
                  const expandedEventsResult = await caldavService.fetchEvents(
                    calendar.url,
                    {
                      timeRange: {
                        start: fetchInfo.start,
                        end: fetchInfo.end,
                      },
                      expand: true,
                    }
                  );

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
      if (calendarRef.current) {
        // @event-calendar/core is Svelte-based and uses $destroy
        const calendar = calendarRef.current as CalendarApi;
        if (typeof calendar.$destroy === 'function') {
          calendar.$destroy();
        }
        calendarRef.current = null;
      }
      // Also clear the container
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [
    isConnected,
    calendarUrl,
    calendarLocale,
    firstDayOfWeek,
    formatDayHeader,
    handleEventClick,
    handleEventDrop,
    handleEventResize,
    handleDateClick,
    handleSelect,
    caldavService,
    adapter,
    setCurrentDate,
    t,
    i18n.language,
    containerRef,
    calendarRef,
    visibleCalendarUrlsRef,
    davCalendarsRef,
  ]);
};

/**
 * Hook to check scheduling capabilities on mount.
 */
export const useSchedulingCapabilitiesCheck = (
  isConnected: boolean,
  caldavService: CalDavService
) => {
  const hasCheckedRef = useRef(false);

  useEffect(() => {
    if (!isConnected || hasCheckedRef.current) return;

    hasCheckedRef.current = true;

    const checkSchedulingCapabilities = async () => {
      const result = await caldavService.getSchedulingCapabilities();

      if (result.success && result.data) {
        console.group('📅 CalDAV Scheduling Capabilities');
        console.log(
          'Scheduling Support:',
          result.data.hasSchedulingSupport ? '✅ Enabled' : '❌ Disabled'
        );
        console.log(
          'Schedule Outbox URL:',
          result.data.scheduleOutboxUrl || '❌ Not found'
        );
        console.log(
          'Schedule Inbox URL:',
          result.data.scheduleInboxUrl || '❌ Not found'
        );
        console.log(
          'Calendar User Addresses:',
          result.data.calendarUserAddressSet.length > 0
            ? result.data.calendarUserAddressSet
            : '❌ None'
        );
        console.log('');
        console.log('Raw server response:', result.data.rawResponse);

        if (result.data.hasSchedulingSupport) {
          console.log('');
          console.log('✉️  Email Notifications Status:');
          console.log('   The server supports CalDAV scheduling (RFC 6638).');
          console.log(
            '   However, this does NOT guarantee email notifications will be sent.'
          );
          console.log(
            '   Email sending requires the IMip plugin to be configured on the server.'
          );
          console.log(
            '   Contact your server administrator to verify IMip plugin configuration.'
          );
        } else {
          console.warn('');
          console.warn(
            '⚠️  CalDAV scheduling properties not found on this server.'
          );
          console.warn('   This could mean:');
          console.warn(
            '   1. The scheduling plugin is not enabled in Sabre/DAV configuration'
          );
          console.warn(
            '   2. The properties are located elsewhere (check raw response above)'
          );
          console.warn(
            '   3. The server does not support CalDAV scheduling (RFC 6638)'
          );
        }

        console.groupEnd();
      } else {
        console.error('Failed to check scheduling capabilities:', result.error);
      }
    };

    checkSchedulingCapabilities();
  }, [isConnected, caldavService]);
};
