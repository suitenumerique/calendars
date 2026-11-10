/**
 * Type definitions for CalendarList components.
 */

import type { CalDavCalendar } from "../../services/dav/types/caldav-service";

/**
 * Props for the CalendarModal component.
 */
export interface CalendarModalProps {
  isOpen: boolean;
  mode: "create" | "edit";
  calendar?: CalDavCalendar | null;
  onClose: () => void;
  onSave: (
    name: string,
    color: string,
    mailboxEmail?: string,
    includeInAvailability?: boolean,
  ) => Promise<void>;
  isOnboarding?: boolean;
  /** Onboarding only: lets the user close the modal without creating a calendar. */
  canDismissOnboarding?: boolean;
}

/**
 * Props for the CalendarItemMenu component.
 */
export interface CalendarItemMenuProps {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  onEdit: () => void;
  /** Asks to confirm the delete for every user. Set it for the owner only. */
  onDelete?: () => void;
  /** Asks to confirm that the user leaves the calendar. Set it for a sharee only. */
  onLeave?: () => void;
  /** Removes the ordinary delete and leave actions, unless onDeleteForMailbox is set. */
  syncManaged?: boolean;
  /**
   * Asks to confirm the delete for every user of the mailbox. Set it for a
   * mailbox admin only. It replaces the delete and leave actions.
   */
  onDeleteForMailbox?: () => void;
  /** Hides the calendar for the user (see `CalDavCalendar.hidden`). Set it for a sharee only. */
  onHide?: () => void;
  onShare?: () => void;
  onImport?: () => void;
  onSubscription?: () => void;
  /** Pass `undefined` when at the bucket boundary to hide the entry. */
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}

export interface DeleteConfirmModalProps {
  /** The calendar to delete or to leave. The modal is open when it is set. */
  calendar: CalDavCalendar | null;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading: boolean;
}

export interface MailboxCalendarDeleteModalProps {
  /** The calendar to delete. The modal is open when it is set. */
  calendar: CalDavCalendar | null;
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
  /** Asks to delete the calendar, or to leave it for a sharee. */
  onDelete: (calendar: CalDavCalendar) => void;
  /** Set it when the user is an admin of the mailbox of the calendar. */
  onDeleteForMailbox?: (calendar: CalDavCalendar) => void;
  /** Hides the calendar for the user (see `CalDavCalendar.hidden`). The item uses it for a sharee only. */
  onHide?: (calendar: CalDavCalendar) => void;
  onShare?: (calendar: CalDavCalendar) => void;
  onImport?: (calendar: CalDavCalendar) => void;
  onSubscription?: (calendar: CalDavCalendar) => void;
  /** Pass `undefined` at the bucket boundary to hide the entry. */
  onMoveUp?: (calendar: CalDavCalendar) => void;
  onMoveDown?: (calendar: CalDavCalendar) => void;
  onCloseMenu: () => void;
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
 * State for the share modal.
 */
export interface ShareModalState {
  isOpen: boolean;
  calendar: CalDavCalendar | null;
}
