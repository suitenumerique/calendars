/**
 * useSchedulerHandlers hook.
 * Provides all event handlers for the Scheduler component.
 */

import { useCallback, MutableRefObject } from "react";
import { IcsEvent } from "ts-ics";

import { useAuth } from "@/features/auth/Auth";
import type {
  EventCalendarEvent,
  EventCalendarSelectInfo,
  EventCalendarEventClickInfo,
  EventCalendarEventDropInfo,
  EventCalendarEventResizeInfo,
  EventCalendarDateClickInfo,
} from "../../../services/dav/types/event-calendar";
import type { EventCalendarAdapter, CalDavExtendedProps } from "../../../services/dav/EventCalendarAdapter";
import type { CalDavService } from "../../../services/dav/CalDavService";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";
import type { EventModalState, RecurringDeleteOption } from "../types";

// Get browser timezone
const BROWSER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

type ECEvent = EventCalendarEvent;

// Calendar API interface (subset of what we need from the calendar instance)
interface CalendarApi {
  updateEvent: (event: ECEvent) => void;
  addEvent: (event: ECEvent) => void;
  unselect: () => void;
  refetchEvents: () => void;
}

interface UseSchedulerHandlersProps {
  adapter: EventCalendarAdapter;
  caldavService: CalDavService;
  davCalendarsRef: MutableRefObject<CalDavCalendar[]>;
  calendarRef: MutableRefObject<CalendarApi | null>;
  calendarUrl: string;
  modalState: EventModalState;
  setModalState: React.Dispatch<React.SetStateAction<EventModalState>>;
}

export const useSchedulerHandlers = ({
  adapter,
  caldavService,
  davCalendarsRef,
  calendarRef,
  calendarUrl,
  modalState,
  setModalState,
}: UseSchedulerHandlersProps) => {
  const { user } = useAuth();

  /**
   * Handle event drop (drag & drop to new time/date).
   * Uses adapter to correctly convert dates with timezone.
   */
  const handleEventDrop = useCallback(
    async (info: EventCalendarEventDropInfo) => {
      const extProps = info.event.extendedProps as CalDavExtendedProps;

      if (!extProps?.eventUrl) {
        console.error("No eventUrl in extendedProps, cannot update");
        info.revert();
        return;
      }

      console.log('[EventDrop] Event:', info.event);
      console.log('[EventDrop] allDay:', info.event.allDay);
      console.log('[EventDrop] start:', info.event.start);
      console.log('[EventDrop] end:', info.event.end);

      try {
        const icsEvent = adapter.toIcsEvent(info.event as EventCalendarEvent, {
          defaultTimezone: extProps.timezone || BROWSER_TIMEZONE,
        });

        console.log('[EventDrop] IcsEvent start:', icsEvent.start);
        console.log('[EventDrop] IcsEvent end:', icsEvent.end);

        const result = await caldavService.updateEvent({
          eventUrl: extProps.eventUrl,
          event: icsEvent,
          etag: extProps.etag,
        });

        if (!result.success) {
          console.error("Failed to update event:", result.error);
          info.revert();
          return;
        }

        // Update etag for next update
        if (result.data?.etag && calendarRef.current) {
          const updatedEvent = {
            ...info.event,
            extendedProps: { ...extProps, etag: result.data.etag },
          };
          calendarRef.current.updateEvent(updatedEvent as ECEvent);
        }
      } catch (error) {
        console.error("Error updating event:", error);
        info.revert();
      }
    },
    [adapter, caldavService, calendarRef]
  );

  /**
   * Handle event resize (change duration).
   */
  const handleEventResize = useCallback(
    async (info: EventCalendarEventResizeInfo) => {
      const extProps = info.event.extendedProps as CalDavExtendedProps;

      if (!extProps?.eventUrl) {
        console.error("No eventUrl in extendedProps, cannot update");
        info.revert();
        return;
      }

      try {
        const icsEvent = adapter.toIcsEvent(info.event as EventCalendarEvent, {
          defaultTimezone: extProps.timezone || BROWSER_TIMEZONE,
        });

        const result = await caldavService.updateEvent({
          eventUrl: extProps.eventUrl,
          event: icsEvent,
          etag: extProps.etag,
        });

        if (!result.success) {
          console.error("Failed to resize event:", result.error);
          info.revert();
          return;
        }

        // Update etag
        if (result.data?.etag && calendarRef.current) {
          const updatedEvent = {
            ...info.event,
            extendedProps: {
              ...extProps,
              etag: result.data.etag,
            },
          };
          calendarRef.current.updateEvent(updatedEvent as ECEvent);
        }
      } catch (error) {
        console.error("Error resizing event:", error);
        info.revert();
      }
    },
    [adapter, caldavService, calendarRef]
  );

  /**
   * Handle event click - open edit modal.
   */
  const handleEventClick = useCallback(
    (info: EventCalendarEventClickInfo) => {
      const extProps = info.event.extendedProps as CalDavExtendedProps;

      // Convert EventCalendar event back to IcsEvent for editing
      const icsEvent = adapter.toIcsEvent(info.event as EventCalendarEvent, {
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
    [adapter, calendarUrl, setModalState]
  );

  /**
   * Handle date click - open create modal for single time slot.
   */
  const handleDateClick = useCallback(
    (info: EventCalendarDateClickInfo) => {
      const start = info.date;
      const end = new Date(start.getTime() + 60 * 60 * 1000); // 1 hour default

      const newEvent: Partial<IcsEvent> = {
        uid: crypto.randomUUID(),
        stamp: { date: new Date() },
        start: {
          date: start,
          type: info.allDay ? "DATE" : "DATE-TIME",
          // Don't set 'local' here - the date is already in browser local time
          // Setting 'local' would make EventModal think it's "fake UTC"
        },
        end: {
          date: end,
          type: info.allDay ? "DATE" : "DATE-TIME",
          // Don't set 'local' here - the date is already in browser local time
        },
      };

      setModalState({
        isOpen: true,
        mode: "create",
        event: newEvent,
        calendarUrl: calendarUrl,
      });
    },
    [calendarUrl, setModalState]
  );

  /**
   * Handle select - open create modal for selected time range.
   */
  const handleSelect = useCallback(
    (info: EventCalendarSelectInfo) => {
      const newEvent: Partial<IcsEvent> = {
        uid: crypto.randomUUID(),
        stamp: { date: new Date() },
        start: {
          date: info.start,
          type: info.allDay ? "DATE" : "DATE-TIME",
          // Don't set 'local' here - the date is already in browser local time
        },
        end: {
          date: info.end,
          type: info.allDay ? "DATE" : "DATE-TIME",
          // Don't set 'local' here - the date is already in browser local time
        },
      };

      setModalState({
        isOpen: true,
        mode: "create",
        event: newEvent,
        calendarUrl: calendarUrl,
      });

      // Clear the selection
      calendarRef.current?.unselect();
    },
    [calendarUrl, calendarRef, setModalState]
  );

  /**
   * Handle modal save (create or update event).
   */
  const handleModalSave = useCallback(
    async (event: IcsEvent, targetCalendarUrl: string) => {
      if (modalState.mode === "create") {
        // Create new event
        const result = await caldavService.createEvent({
          calendarUrl: targetCalendarUrl,
          event,
        });

        if (!result.success) {
          throw new Error(result.error || "Failed to create event");
        }

        // Add to calendar UI
        if (calendarRef.current && result.data) {
          // For recurring events, refetch all events to ensure proper timezone conversion
          if (event.recurrenceRule) {
            calendarRef.current.refetchEvents();
          } else {
            // Non-recurring event, add normally
            const calendarColors = adapter.createCalendarColorMap(
              davCalendarsRef.current
            );
            const ecEvents = adapter.toEventCalendarEvents([result.data], {
              calendarColors,
            });
            if (ecEvents.length > 0) {
              calendarRef.current.addEvent(ecEvents[0] as ECEvent);
            }
          }
        }
      } else {
        // Update existing event
        if (!modalState.eventUrl) {
          throw new Error("No event URL for update");
        }

        const result = await caldavService.updateEvent({
          eventUrl: modalState.eventUrl,
          event,
          etag: modalState.etag,
        });

        if (!result.success) {
          throw new Error(result.error || "Failed to update event");
        }

        // Update in calendar UI
        if (calendarRef.current && result.data) {
          // If this is a recurring event, refetch all events to update all instances
          if (event.recurrenceRule) {
            calendarRef.current.refetchEvents();
          } else {
            // Non-recurring event, update normally
            const calendarColors = adapter.createCalendarColorMap(
              davCalendarsRef.current
            );
            const ecEvents = adapter.toEventCalendarEvents([result.data], {
              calendarColors,
            });
            if (ecEvents.length > 0) {
              calendarRef.current.updateEvent(ecEvents[0] as ECEvent);
            }
          }
        }
      }
    },
    [adapter, caldavService, calendarRef, davCalendarsRef, modalState]
  );

  /**
   * Handle modal delete.
   */
  const handleModalDelete = useCallback(
    async (
      event: IcsEvent,
      _targetCalendarUrl: string,
      option?: RecurringDeleteOption
    ) => {
      if (!modalState.eventUrl) {
        throw new Error("No event URL for delete");
      }

      // If this is a recurring event and we have an option
      if (event.recurrenceRule && option && option !== 'all') {
        // Get the occurrence date
        // Prefer recurrenceId if available (it identifies this specific occurrence)
        // Otherwise fall back to start date
        let occurrenceDate: Date;
        if (event.recurrenceId?.value?.date) {
          occurrenceDate = event.recurrenceId.value.date;
        } else if (event.start.date instanceof Date) {
          occurrenceDate = event.start.date;
        } else {
          occurrenceDate = new Date(event.start.date);
        }

        if (option === 'this') {
          // Option 1: Delete only this occurrence - Add EXDATE
          const addExdateResult = await caldavService.addExdateToEvent(
            modalState.eventUrl,
            occurrenceDate,
            modalState.etag
          );

          if (!addExdateResult.success) {
            throw new Error(addExdateResult.error || "Failed to add EXDATE");
          }

          // Refetch events to update UI
          if (calendarRef.current) {
            calendarRef.current.refetchEvents();
          }
        } else if (option === 'future') {
          // Option 2: Delete this and future occurrences - Modify UNTIL
          const fetchResult = await caldavService.fetchEvent(modalState.eventUrl);

          if (!fetchResult.success || !fetchResult.data) {
            throw new Error("Failed to fetch source event");
          }

          const sourceIcsEvents = fetchResult.data.data.events ?? [];
          const sourceEvent = sourceIcsEvents.find(
            (e) => e.uid === event.uid && !e.recurrenceId
          );

          if (!sourceEvent || !sourceEvent.recurrenceRule) {
            throw new Error("Source event or recurrence rule not found");
          }

          // Set UNTIL to the day before this occurrence
          const untilDate = new Date(occurrenceDate);
          untilDate.setDate(untilDate.getDate() - 1);
          untilDate.setHours(23, 59, 59, 999);

          const updatedRecurrenceRule = {
            ...sourceEvent.recurrenceRule,
            until: {
              type: 'DATE-TIME' as const,
              date: untilDate,
            },
            count: undefined, // Remove count if present
          };

          const updatedEvent: IcsEvent = {
            ...sourceEvent,
            recurrenceRule: updatedRecurrenceRule,
          };

          const updateResult = await caldavService.updateEvent({
            eventUrl: modalState.eventUrl,
            event: updatedEvent,
            etag: modalState.etag,
          });

          if (!updateResult.success) {
            throw new Error(updateResult.error || "Failed to update event");
          }

          // Refetch events to update UI
          if (calendarRef.current) {
            calendarRef.current.refetchEvents();
          }
        }
      } else {
        // Option 3: Delete all occurrences OR non-recurring event
        const result = await caldavService.deleteEvent(modalState.eventUrl);

        if (!result.success) {
          throw new Error(result.error || "Failed to delete event");
        }

        // Refetch events to update UI
        if (calendarRef.current) {
          calendarRef.current.refetchEvents();
        }
      }
    },
    [caldavService, modalState, calendarRef]
  );

  /**
   * Handle modal close.
   */
  const handleModalClose = useCallback(() => {
    setModalState((prev) => ({ ...prev, isOpen: false }));
  }, [setModalState]);

  /**
   * Handle respond to invitation.
   */
  const handleRespondToInvitation = useCallback(
    async (event: IcsEvent, status: 'ACCEPTED' | 'TENTATIVE' | 'DECLINED') => {
      if (!user?.email) {
        console.error('No user email available');
        return;
      }

      if (!modalState.eventUrl) {
        console.error('No event URL available');
        return;
      }

      try {
        const result = await caldavService.respondToMeeting(
          modalState.eventUrl,
          event,
          user.email,
          status,
          modalState.etag
        );

        if (!result.success) {
          throw new Error(result.error || 'Failed to respond to invitation');
        }

        console.log('✉️ Response sent successfully:', status);

        // Refetch events to update the UI with the new status
        if (calendarRef.current) {
          calendarRef.current.refetchEvents();
        }

        // Close the modal
        setModalState((prev) => ({ ...prev, isOpen: false }));
      } catch (error) {
        console.error('Error responding to invitation:', error);
        throw error;
      }
    },
    [caldavService, user, calendarRef, modalState.eventUrl, modalState.etag, setModalState]
  );

  return {
    handleEventDrop,
    handleEventResize,
    handleEventClick,
    handleDateClick,
    handleSelect,
    handleModalSave,
    handleModalDelete,
    handleModalClose,
    handleRespondToInvitation,
  };
};
