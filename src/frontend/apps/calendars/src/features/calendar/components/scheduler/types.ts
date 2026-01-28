/**
 * Type definitions for Scheduler components.
 */

import type { IcsEvent, IcsRecurrenceRule } from "ts-ics";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import type { EventCalendarAdapter } from "../../services/dav/EventCalendarAdapter";

/**
 * Options for deleting recurring events.
 */
export type RecurringDeleteOption = 'this' | 'future' | 'all';

/**
 * Props for the EventModal component.
 */
export interface EventModalProps {
  isOpen: boolean;
  mode: "create" | "edit";
  event: Partial<IcsEvent> | null;
  calendarUrl: string;
  calendars: CalDavCalendar[];
  adapter: EventCalendarAdapter;
  onSave: (event: IcsEvent, calendarUrl: string) => Promise<void>;
  onDelete?: (
    event: IcsEvent,
    calendarUrl: string,
    option?: RecurringDeleteOption
  ) => Promise<void>;
  onRespondToInvitation?: (
    event: IcsEvent,
    status: 'ACCEPTED' | 'TENTATIVE' | 'DECLINED'
  ) => Promise<void>;
  onClose: () => void;
}

/**
 * Props for the DeleteEventModal component.
 */
export interface DeleteEventModalProps {
  isOpen: boolean;
  isRecurring: boolean;
  onConfirm: (option?: RecurringDeleteOption) => void;
  onCancel: () => void;
}

/**
 * Props for the main Scheduler component.
 */
export interface SchedulerProps {
  defaultCalendarUrl?: string;
}

/**
 * State for the event modal.
 */
export interface EventModalState {
  isOpen: boolean;
  mode: "create" | "edit";
  event: Partial<IcsEvent> | null;
  calendarUrl: string;
  eventUrl?: string;
  etag?: string;
}

/**
 * Form state for the event modal.
 */
export interface EventFormState {
  title: string;
  description: string;
  location: string;
  startDateTime: string;
  endDateTime: string;
  selectedCalendarUrl: string;
  isAllDay: boolean;
  recurrence: IcsRecurrenceRule | undefined;
  showRecurrence: boolean;
  showAttendees: boolean;
}

/**
 * Calendar API interface for toolbar interactions.
 */
export interface CalendarApi {
  setOption: (name: string, value: unknown) => void;
  getOption: (name: string) => unknown;
  getView: () => { type: string; title: string; currentStart: Date; currentEnd: Date };
  prev: () => void;
  next: () => void;
  updateEvent: (event: unknown) => void;
  addEvent: (event: unknown) => void;
  unselect: () => void;
  refetchEvents: () => void;
  $destroy?: () => void;
}

/**
 * Props for the SchedulerToolbar component.
 */
export interface SchedulerToolbarProps {
  calendarRef: React.RefObject<CalendarApi | null>;
  currentView: string;
  viewTitle: string;
  onViewChange?: (view: string) => void;
}
