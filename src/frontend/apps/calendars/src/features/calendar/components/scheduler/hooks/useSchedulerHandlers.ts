/**
 * useSchedulerHandlers hook.
 * Provides all event handlers for the Scheduler component.
 */

import { useCallback, useState, MutableRefObject } from "react";
import { IcsEvent, IcsDateObject } from "ts-ics";

import { useAuth } from "@/features/auth/Auth";
import { addErrorToast } from "@/features/ui/components/toaster/Toaster";
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
import { getCalendarUrlFromEventUrl } from "../../../services/dav/caldav-helpers";
import type {
  EventModalState,
  RecurringDeleteOption,
  RecurringEditOption,
} from "../types";

// Get browser timezone
const BROWSER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

/**
 * Merge source event's date (year/month/day) with form event's time
 * (hours/minutes/seconds). Both use the "fake UTC" pattern where
 * UTC components represent local timezone values.
 */
function mergeSourceDateWithFormTime(
  sourceDate: IcsDateObject,
  formDate: IcsDateObject,
): IcsDateObject {
  const src = sourceDate.date;
  const frm = formDate.date;

  const merged = new Date(
    Date.UTC(
      src.getUTCFullYear(),
      src.getUTCMonth(),
      src.getUTCDate(),
      frm.getUTCHours(),
      frm.getUTCMinutes(),
      frm.getUTCSeconds(),
    ),
  );

  return {
    ...formDate,
    date: merged,
    local: formDate.local
      ? {
          ...formDate.local,
          date: merged,
        }
      : undefined,
  };
}

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
  calendarRef: MutableRefObject<CalendarApi | null>;
  calendarUrl: string;
  modalState: EventModalState;
  setModalState: React.Dispatch<React.SetStateAction<EventModalState>>;
}

/**
 * Pending recurring action for drag-and-drop or resize operations.
 * Stored so the recurring edit modal can resolve it.
 */
export interface PendingRecurringAction {
  type: 'drop' | 'resize';
  info: EventCalendarEventDropInfo | EventCalendarEventResizeInfo;
}

export const useSchedulerHandlers = ({
  adapter,
  caldavService,
  calendarRef,
  calendarUrl,
  modalState,
  setModalState,
}: UseSchedulerHandlersProps) => {
  const { user } = useAuth();
  const [pendingRecurringAction, setPendingRecurringAction] =
    useState<PendingRecurringAction | null>(null);

  /**
   * Handle event drop (drag & drop to new time/date).
   * For recurring events, shows a prompt before applying changes.
   */
  const handleEventDrop = useCallback(
    async (info: EventCalendarEventDropInfo) => {
      const extProps = info.event.extendedProps as CalDavExtendedProps;

      if (!extProps?.eventUrl) {
        console.error("No eventUrl in extendedProps, cannot update");
        info.revert();
        return;
      }

      // If recurring, defer to the recurring edit modal
      if (extProps.recurrenceRule) {
        setPendingRecurringAction({ type: 'drop', info });
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
          console.error("Failed to update event:", result.error);
          info.revert();
          return;
        }

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
   * For recurring events, shows a prompt before applying changes.
   */
  const handleEventResize = useCallback(
    async (info: EventCalendarEventResizeInfo) => {
      const extProps = info.event.extendedProps as CalDavExtendedProps;

      if (!extProps?.eventUrl) {
        console.error("No eventUrl in extendedProps, cannot update");
        info.revert();
        return;
      }

      // If recurring, defer to the recurring edit modal
      if (extProps.recurrenceRule) {
        setPendingRecurringAction({ type: 'resize', info });
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
   * For recurring events, `option` determines the scope of the edit.
   */
  const handleModalSave = useCallback(
    async (
      event: IcsEvent,
      targetCalendarUrl: string,
      option?: RecurringEditOption,
    ) => {
      if (modalState.mode === "create") {
        const result = await caldavService.createEvent({
          calendarUrl: targetCalendarUrl,
          event,
        });

        if (!result.success) {
          throw new Error(result.error || "Failed to create event");
        }

        if (calendarRef.current) {
          calendarRef.current.refetchEvents();
        }
        return;
      }

      // Edit mode
      if (!modalState.eventUrl) {
        throw new Error("No event URL for update");
      }

      // Use the ORIGINAL event (before user edits) for occurrence date.
      // The form-built event has potentially modified dates.
      const originalEvent = modalState.event;

      /**
       * Get occurrence date from the original modal event (fake UTC).
       */
      const getOccurrenceDate = (): Date => {
        if (originalEvent?.recurrenceId?.value?.date) {
          return originalEvent.recurrenceId.value.date;
        }
        if (originalEvent?.start?.date instanceof Date) {
          return originalEvent.start.date;
        }
        if (originalEvent?.start?.date) {
          return new Date(originalEvent.start.date);
        }
        // Fallback to form event start
        return event.start.date instanceof Date
          ? event.start.date
          : new Date(event.start.date);
      };

      if (option === 'this') {
        // Create an override instance for this occurrence only
        const occurrenceDate = getOccurrenceDate();

        const result = await caldavService.createOverrideInstance(
          modalState.eventUrl,
          event,
          occurrenceDate,
          modalState.etag,
        );

        if (!result.success) {
          throw new Error(result.error || "Failed to create override instance");
        }
      } else if (option === 'future') {
        // Truncate the original series and create a new recurring series
        const fetchResult = await caldavService.fetchEvent(modalState.eventUrl);
        if (!fetchResult.success || !fetchResult.data) {
          throw new Error("Failed to fetch source event");
        }

        const sourceIcsEvents = fetchResult.data.data.events ?? [];
        const sourceEvent = sourceIcsEvents.find(
          (e) => e.uid === event.uid && !e.recurrenceId,
        );

        if (!sourceEvent) {
          throw new Error("Source event not found");
        }

        // Use the ORIGINAL occurrence date for the UNTIL boundary
        const occurrenceDate = getOccurrenceDate();

        // Truncate the original series: sets UNTIL, removes overrides and
        // EXDATEs >= cutoff in one atomic PUT (prevents orphan overrides).
        const truncateResult = await caldavService.truncateRecurringSeries(
          modalState.eventUrl,
          occurrenceDate,
          event.uid,
          fetchResult.data.etag,
        );

        if (!truncateResult.success) {
          throw new Error(truncateResult.error || "Failed to truncate series");
        }

        // Create a new recurring event starting from the modified occurrence
        const newSeriesEvent: IcsEvent = {
          ...event,
          uid: crypto.randomUUID(),
          recurrenceId: undefined,
          recurrenceRule: sourceEvent.recurrenceRule,
          sequence: 0,
        };

        const createResult = await caldavService.createEvent({
          calendarUrl: targetCalendarUrl,
          event: newSeriesEvent,
        });

        if (!createResult.success) {
          throw new Error(createResult.error || "Failed to create new series");
        }
      } else {
        // 'all' or undefined: update the entire event/series.
        let eventToUpdate = event;
        let etag = modalState.etag;

        const isRecurring = !!event.recurrenceRule;
        const fetchResult = await caldavService.fetchEvent(modalState.eventUrl);
        if (fetchResult.success && fetchResult.data) {
          const sourceEvents = fetchResult.data.data.events ?? [];
          const sourceEvent = sourceEvents.find(
            (e) => e.uid === event.uid && !e.recurrenceId,
          );
          if (sourceEvent) {
            if (isRecurring) {
              // Recurring series: keep sourceEvent's date to preserve DTSTART,
              // but apply user's time changes (hours/minutes) from the form.
              const mergedStart = mergeSourceDateWithFormTime(
                sourceEvent.start,
                event.start,
              );
              const mergedEnd = event.end
                ? mergeSourceDateWithFormTime(sourceEvent.end!, event.end)
                : undefined;

              eventToUpdate = {
                ...event,
                start: mergedStart,
                end: mergedEnd,
                duration: sourceEvent.duration,
                recurrenceId: undefined,
                exceptionDates: sourceEvent.exceptionDates,
              } as IcsEvent;
            } else {
              // Non-recurring: use form dates directly (user can change date)
              eventToUpdate = {
                ...event,
                duration: sourceEvent.duration,
              } as IcsEvent;
            }
          }
          etag = fetchResult.data.etag;
        }

        const sourceCalendarUrl = getCalendarUrlFromEventUrl(modalState.eventUrl);

        // Calendar change: WebDAV MOVE relocates the resource without firing
        // iTIP (Sabre's Schedule plugin skips it on MOVE), so attendees don't
        // get spurious REQUEST/CANCEL emails. Then a normal PUT at the new
        // URL applies any content edits — iTIP dispatches only on a
        // significant change, as it would for any in-place edit.
        let updateUrl = modalState.eventUrl;
        let updateEtag = etag;
        if (sourceCalendarUrl !== targetCalendarUrl) {
          const moveResult = await caldavService.moveEvent({
            sourceEventUrl: modalState.eventUrl,
            targetCalendarUrl,
            sourceEtag: etag,
          });

          if (!moveResult.success || !moveResult.data) {
            throw new Error(moveResult.error || "Failed to move event");
          }

          updateUrl = moveResult.data.url;
          updateEtag = moveResult.data.etag;
        }

        const result = await caldavService.updateEvent({
          eventUrl: updateUrl,
          event: eventToUpdate,
          etag: updateEtag,
        });

        if (!result.success) {
          throw new Error(result.error || "Failed to update event");
        }
      }

      if (calendarRef.current) {
        calendarRef.current.refetchEvents();
      }
    },
    [caldavService, calendarRef, modalState.mode, modalState.eventUrl, modalState.etag, modalState.event]
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
          // Delete only this occurrence
          let shouldDeleteEntireEvent = false;

          if (event.recurrenceId) {
            // This is an override instance — remove the override VEVENT
            // and ensure EXDATE exists on the source event
            const deleteResult = await caldavService.deleteOverrideInstance(
              modalState.eventUrl,
              occurrenceDate,
              event.uid,
              modalState.etag
            );

            if (!deleteResult.success) {
              throw new Error(deleteResult.error || "Failed to delete override instance");
            }
            shouldDeleteEntireEvent = !!deleteResult.data?.shouldDeleteEntireEvent;
          } else {
            // Regular occurrence (not an override) — just add EXDATE
            const addExdateResult = await caldavService.addExdateToEvent(
              modalState.eventUrl,
              occurrenceDate,
              modalState.etag
            );

            if (!addExdateResult.success) {
              throw new Error(addExdateResult.error || "Failed to add EXDATE");
            }
            shouldDeleteEntireEvent = !!addExdateResult.data?.shouldDeleteEntireEvent;
          }

          // If the EXDATE would leave zero occurrences, delete entirely
          if (shouldDeleteEntireEvent) {
            const fullDeleteResult = await caldavService.deleteEvent(
              modalState.eventUrl,
              modalState.etag,
            );
            if (!fullDeleteResult.success) {
              throw new Error(fullDeleteResult.error || "Failed to delete event");
            }
          }

          // Refetch events to update UI
          if (calendarRef.current) {
            calendarRef.current.refetchEvents();
          }
        } else if (option === 'future') {
          // Fetch source event to check if this is the first occurrence
          const fetchResult = await caldavService.fetchEvent(modalState.eventUrl);
          const sourceEvents = fetchResult.success && fetchResult.data
            ? (fetchResult.data.data.events ?? [])
            : [];
          const sourceEvent = sourceEvents.find(
            (e) => e.uid === event.uid && !e.recurrenceId,
          );

          // If deleting from first occurrence, delete entire series
          // Use local.date (fake UTC) to match occurrenceDate format (also fake UTC)
          const sourceStartDate = sourceEvent?.start.local?.date ?? sourceEvent?.start.date;
          if (sourceEvent && sourceStartDate && occurrenceDate.getTime() <= sourceStartDate.getTime()) {
            const deleteResult = await caldavService.deleteEvent(
              modalState.eventUrl,
              modalState.etag,
            );
            if (!deleteResult.success) {
              throw new Error(deleteResult.error || "Failed to delete event");
            }
          } else {
            const truncateResult = await caldavService.truncateRecurringSeries(
              modalState.eventUrl,
              occurrenceDate,
              event.uid,
              modalState.etag,
            );
            if (!truncateResult.success) {
              throw new Error(truncateResult.error || "Failed to truncate series");
            }
          }

          if (calendarRef.current) {
            calendarRef.current.refetchEvents();
          }
        }
      } else {
        // Option 3: Delete all occurrences OR non-recurring event
        const result = await caldavService.deleteEvent(modalState.eventUrl, modalState.etag);

        if (!result.success) {
          throw new Error(result.error || "Failed to delete event");
        }

        // Refetch events to update UI
        if (calendarRef.current) {
          calendarRef.current.refetchEvents();
        }
      }
    },
    [caldavService, calendarRef, modalState.eventUrl, modalState.etag]
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

  /**
   * Get the occurrence date (in fake UTC) from a drag/resize info.
   * Uses the OLD event (before drag/resize) converted through the adapter
   * so the date matches the DTSTART format used in the ICS.
   */
  const getOccurrenceDateFromInfo = useCallback(
    (
      info: EventCalendarEventDropInfo | EventCalendarEventResizeInfo,
      extProps: CalDavExtendedProps,
    ): Date | null => {
      const tz = extProps.timezone || BROWSER_TIMEZONE;

      // If already an override instance, use its recurrenceId.
      // SabreDAV expand returns recurrenceId in real UTC, but we need fake UTC
      // (UTC components = local timezone time) for EXDATE/RECURRENCE-ID generation.
      if (extProps.recurrenceId) {
        // For all-day events, recurrenceId from SabreDAV is already midnight UTC
        // representing a pure date. No timezone conversion needed (would corrupt it).
        if (info.event.allDay) {
          return new Date(Date.UTC(
            extProps.recurrenceId.getUTCFullYear(),
            extProps.recurrenceId.getUTCMonth(),
            extProps.recurrenceId.getUTCDate(),
          ));
        }
        // For timed events, convert real UTC → fake UTC
        const components = adapter.getDateComponentsInTimezone(
          extProps.recurrenceId,
          tz,
        );
        return new Date(Date.UTC(
          components.year,
          components.month - 1,
          components.day,
          components.hours,
          components.minutes,
          components.seconds,
        ));
      }

      // Convert the old event through the adapter to get fake UTC date
      const oldEvent = 'oldEvent' in info
        ? (info.oldEvent as EventCalendarEvent | undefined)
        : undefined;

      if (oldEvent) {
        const oldIcsEvent = adapter.toIcsEvent(oldEvent, {
          defaultTimezone: tz,
        });
        const result = oldIcsEvent.start.date instanceof Date
          ? oldIcsEvent.start.date
          : new Date(oldIcsEvent.start.date);
        return result;
      }

      return null;
    },
    [adapter],
  );

  /**
   * Handle confirming a recurring edit for pending drag-drop/resize.
   */
  const handlePendingRecurringConfirm = useCallback(
    async (option: RecurringEditOption) => {
      if (!pendingRecurringAction) return;

      const info = pendingRecurringAction.info;
      const extProps = info.event.extendedProps as CalDavExtendedProps;
      setPendingRecurringAction(null);

      if (!extProps?.eventUrl) {
        info.revert();
        return;
      }

      const eventUrl = extProps.eventUrl;
      const tz = extProps.timezone || BROWSER_TIMEZONE;

      try {
        if (option === 'this') {
          // Get occurrence date from BEFORE the drag/resize (in fake UTC)
          const occurrenceDate = getOccurrenceDateFromInfo(info, extProps);
          if (!occurrenceDate) {
            info.revert();
            return;
          }

          // Convert the NEW event (after drag/resize) to ICS
          const newIcsEvent = adapter.toIcsEvent(
            info.event as EventCalendarEvent,
            { defaultTimezone: tz },
          );

          const result = await caldavService.createOverrideInstance(
            eventUrl,
            newIcsEvent,
            occurrenceDate,
            extProps.etag,
          );

          if (!result.success) {
            addErrorToast(result.error || "Failed to update event");
            info.revert();
            return;
          }
        } else if (option === 'future') {
          // Get occurrence date from BEFORE the drag/resize
          const occurrenceDate = getOccurrenceDateFromInfo(info, extProps);
          if (!occurrenceDate) {
            info.revert();
            return;
          }

          // Fetch source event from server
          const fetchResult = await caldavService.fetchEvent(eventUrl);
          if (!fetchResult.success || !fetchResult.data) {
            addErrorToast("Failed to fetch event");
            info.revert();
            return;
          }

          const sourceIcsEvents = fetchResult.data.data.events ?? [];
          const sourceEvent = sourceIcsEvents.find(
            (e) => e.uid === extProps.uid && !e.recurrenceId,
          );

          if (!sourceEvent) {
            addErrorToast("Source event not found");
            info.revert();
            return;
          }

          // Truncate the original series: sets UNTIL, removes overrides and
          // EXDATEs >= cutoff in one atomic PUT (prevents orphan overrides).
          const truncateResult = await caldavService.truncateRecurringSeries(
            eventUrl,
            occurrenceDate,
            extProps.uid,
            fetchResult.data.etag,
          );

          if (!truncateResult.success) {
            addErrorToast(truncateResult.error || "Failed to truncate series");
            info.revert();
            return;
          }

          // Create new series with the dragged event's new times
          const newIcsEvent = adapter.toIcsEvent(
            info.event as EventCalendarEvent,
            { defaultTimezone: tz },
          );

          const newSeriesEvent: IcsEvent = {
            ...newIcsEvent,
            uid: crypto.randomUUID(),
            recurrenceId: undefined,
            recurrenceRule: sourceEvent.recurrenceRule,
            sequence: 0,
          };

          const calUrl = extProps.calendarUrl || calendarUrl;
          const createResult = await caldavService.createEvent({
            calendarUrl: calUrl,
            event: newSeriesEvent,
          });

          if (!createResult.success) {
            addErrorToast(createResult.error || "Failed to create new series");
            info.revert();
            return;
          }
        } else {
          // 'all': Fetch source event, compute delta, apply to source
          // This preserves RRULE, EXDATE, and all other ICS properties.
          const fetchResult = await caldavService.fetchEvent(eventUrl);
          if (!fetchResult.success || !fetchResult.data) {
            addErrorToast("Failed to fetch event");
            info.revert();
            return;
          }

          const sourceIcsEvents = fetchResult.data.data.events ?? [];
          const sourceEvent = sourceIcsEvents.find(
            (e) => e.uid === extProps.uid && !e.recurrenceId,
          );

          if (!sourceEvent) {
            addErrorToast("Source event not found");
            info.revert();
            return;
          }

          // Compute time delta from old→new position
          // (browser-local ms delta = same delta in any timezone)
          const oldEvent = 'oldEvent' in info
            ? (info.oldEvent as EventCalendarEvent | undefined)
            : undefined;

          if (!oldEvent) {
            info.revert();
            return;
          }

          const oldStartMs = oldEvent.start instanceof Date
            ? oldEvent.start.getTime()
            : new Date(oldEvent.start).getTime();
          const newStartMs = info.event.start instanceof Date
            ? (info.event.start as Date).getTime()
            : new Date(info.event.start as string).getTime();
          const startDeltaMs = newStartMs - oldStartMs;

          let endDeltaMs = startDeltaMs;
          if (oldEvent.end && info.event.end) {
            const oldEndMs = oldEvent.end instanceof Date
              ? oldEvent.end.getTime()
              : new Date(oldEvent.end).getTime();
            const newEndMs = info.event.end instanceof Date
              ? (info.event.end as Date).getTime()
              : new Date(info.event.end as string).getTime();
            endDeltaMs = newEndMs - oldEndMs;
          }

          // Apply delta separately to .date (TRUE UTC) and .local.date (FAKE UTC)
          // to preserve the timezone model used by ts-ics/generateIcsCalendar
          const newStartDate = new Date(
            sourceEvent.start.date.getTime() + startDeltaMs,
          );

          const updatedEvent: IcsEvent = {
            ...sourceEvent,
            start: {
              ...sourceEvent.start,
              date: newStartDate,
              local: sourceEvent.start.local ? {
                ...sourceEvent.start.local,
                date: new Date(
                  sourceEvent.start.local.date.getTime() + startDeltaMs,
                ),
              } : undefined,
            },
          };

          if (sourceEvent.end) {
            const newEndDate = new Date(
              sourceEvent.end.date.getTime() + endDeltaMs,
            );
            updatedEvent.end = {
              ...sourceEvent.end,
              date: newEndDate,
              local: sourceEvent.end.local ? {
                ...sourceEvent.end.local,
                date: new Date(
                  sourceEvent.end.local.date.getTime() + endDeltaMs,
                ),
              } : undefined,
            };
          }

          const result = await caldavService.updateEvent({
            eventUrl,
            event: updatedEvent,
            etag: fetchResult.data.etag,
          });

          if (!result.success) {
            addErrorToast(result.error || "Failed to update event");
            info.revert();
            return;
          }
        }

        if (calendarRef.current) {
          calendarRef.current.refetchEvents();
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to update event";
        addErrorToast(message);
        info.revert();
      }
    },
    [pendingRecurringAction, adapter, caldavService, calendarRef, calendarUrl, getOccurrenceDateFromInfo]
  );

  /**
   * Cancel a pending recurring action (revert the drag/resize).
   */
  const handlePendingRecurringCancel = useCallback(() => {
    if (pendingRecurringAction) {
      pendingRecurringAction.info.revert();
      setPendingRecurringAction(null);
    }
  }, [pendingRecurringAction]);

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
    pendingRecurringAction,
    handlePendingRecurringConfirm,
    handlePendingRecurringCancel,
  };
};
