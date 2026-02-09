/**
 * Type definitions for CalendarList components.
 */

import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import type { Calendar } from "../../types";

/**
 * Props for the CalendarModal component.
 */
export interface CalendarModalProps {
  isOpen: boolean;
  mode: "create" | "edit";
  calendar?: CalDavCalendar | null;
  onClose: () => void;
  onSave: (name: string, color: string, description?: string) => Promise<void>;
  onShare?: (email: string) => Promise<{ success: boolean; error?: string }>;
}

/**
 * Props for the CalendarItemMenu component.
 */
export interface CalendarItemMenuProps {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
  onImport?: () => void;
  onSubscription?: () => void;
}

/**
 * Props for the DeleteConfirmModal component.
 */
export interface DeleteConfirmModalProps {
  isOpen: boolean;
  calendarName: string;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading: boolean;
}

/**
 * Props for the CalendarListItem component.
 */
export interface CalendarListItemProps {
  calendar: CalDavCalendar;
  isVisible: boolean;
  isMenuOpen: boolean;
  onToggleVisibility: (url: string) => void;
  onMenuToggle: (url: string) => void;
  onEdit: (calendar: CalDavCalendar) => void;
  onDelete: (calendar: CalDavCalendar) => void;
  onImport?: (calendar: CalDavCalendar) => void;
  onSubscription?: (calendar: CalDavCalendar) => void;
  onCloseMenu: () => void;
}

/**
 * Props for the SharedCalendarListItem component.
 */
export interface SharedCalendarListItemProps {
  calendar: Calendar;
  isVisible: boolean;
  onToggleVisibility: (id: string) => void;
}

/**
 * Props for the main CalendarList component.
 */
export interface CalendarListProps {
  calendars: Calendar[];
}

/**
 * State for the calendar modal.
 */
export interface CalendarModalState {
  isOpen: boolean;
  mode: "create" | "edit";
  calendar: CalDavCalendar | null;
}

/**
 * State for the delete confirmation.
 */
export interface DeleteState {
  isOpen: boolean;
  calendar: CalDavCalendar | null;
  isLoading: boolean;
}
