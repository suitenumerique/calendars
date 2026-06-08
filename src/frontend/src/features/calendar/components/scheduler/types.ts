/**
 * Type definitions for Scheduler components.
 */

import type {
  IcsEvent,
  IcsRecurrenceRule,
  IcsAlarm,
  IcsAttendee,
  IcsClassType,
  IcsEventStatusType,
  IcsTimeTransparentType,
} from "ts-ics";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import type { EventCalendarAdapter } from "../../services/dav/EventCalendarAdapter";

/**
 * Options for deleting recurring events.
 */
export type RecurringDeleteOption = "this" | "future" | "all";

/**
 * Options for editing recurring events.
 */
export type RecurringEditOption = "this" | "future" | "all";

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
  onSave: (event: IcsEvent, calendarUrl: string, option?: RecurringEditOption) => Promise<void>;
  onDelete?: (
    event: IcsEvent,
    calendarUrl: string,
    option?: RecurringDeleteOption,
  ) => Promise<void>;
  onRespondToInvitation?: (
    event: IcsEvent,
    status: "ACCEPTED" | "TENTATIVE" | "DECLINED",
    option?: RecurringEditOption,
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
 * Props for the RecurringEditModal component.
 */
export interface RecurringEditModalProps {
  isOpen: boolean;
  onConfirm: (option: RecurringEditOption) => void;
  onCancel: () => void;
  title?: string;
  prompt?: string;
  confirmLabel?: string;
  disableFuture?: boolean;
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
 * Sections toggled via pills in the event modal.
 */
export type EventFormSectionId =
  | "location"
  | "description"
  | "recurrence"
  | "attendees"
  | "resources"
  | "videoConference"
  | "scheduling"
  | "visibility";

/**
 * Attachment metadata (UI only, no actual file upload).
 */
export interface AttachmentMeta {
  id: string;
  name: string;
  size: number;
  type: string;
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
  attendees: IcsAttendee[];
  recurrence: IcsRecurrenceRule | undefined;
  alarms: IcsAlarm[];
  videoConferenceUrl: string;
  attachments: AttachmentMeta[];
  status: IcsEventStatusType;
  visibility: IcsClassType;
  availability: IcsTimeTransparentType;
  expandedSections: Set<EventFormSectionId>;
}

/**
 * Calendar API interface for toolbar interactions.
 */
export interface CalendarApi {
  setOption: (name: string, value: unknown) => void;
  getOption: (name: string) => unknown;
  getView: () => {
    type: string;
    title: string;
    currentStart: Date;
    currentEnd: Date;
  };
  prev: () => void;
  next: () => void;
  updateEvent: (event: unknown) => void;
  addEvent: (event: unknown) => void;
  unselect: () => void;
  refetchEvents: () => void;
  getEvents: () => Array<{
    id: string | number;
    title?: string | { html: string } | { domNodes: Node[] };
    start: Date | string;
    end?: Date | string;
    allDay?: boolean;
    backgroundColor?: string;
    extendedProps?: Record<string, unknown>;
  }>;
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

/**
 * Props for the MobileToolbar component.
 */
export interface MobileToolbarProps {
  calendarRef: React.RefObject<CalendarApi | null>;
  currentView: string;
  currentDate: Date;
  onViewChange: (view: string) => void;
  onWeekPrev: () => void;
  onWeekNext: () => void;
  onTodayClick: () => void;
}

/**
 * Props for the WeekDayBar component.
 */
export interface WeekDayBarProps {
  currentDate: Date;
  currentView: string;
  intlLocale: string;
  weekDays: Date[];
  onDayClick: (date: Date) => void;
}

/**
 * Props for the FloatingActionButton component.
 */
export interface FloatingActionButtonProps {
  onClick: () => void;
}

/**
 * Props for the MobileListView component.
 */
export interface MobileListEvent {
  id: string | number;
  title: string;
  start: Date;
  end: Date;
  allDay: boolean;
  backgroundColor: string;
  extendedProps: Record<string, unknown>;
}

export interface MobileListViewProps {
  weekDays: Date[];
  events: MobileListEvent[];
  intlLocale: string;
  onEventClick: (eventId: string, extendedProps: Record<string, unknown>) => void;
}
