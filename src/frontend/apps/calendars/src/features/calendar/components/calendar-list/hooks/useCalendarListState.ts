/**
 * useCalendarListState hook.
 * Manages state and handlers for the CalendarList component.
 */

import { useState, useCallback } from "react";

import type {
  CalDavCalendar,
  CalDavCalendarCreate,
  CalDavCalendarUpdate,
} from "../../../services/dav/types/caldav-service";
import type { CalendarModalState, DeleteState } from "../types";

interface UseCalendarListStateProps {
  createCalendar: (
    params: CalDavCalendarCreate
  ) => Promise<{ success: boolean; error?: string }>;
  updateCalendar: (
    url: string,
    options: CalDavCalendarUpdate
  ) => Promise<{ success: boolean; error?: string }>;
  deleteCalendar: (url: string) => Promise<{ success: boolean; error?: string }>;
  shareCalendar: (
    url: string,
    email: string
  ) => Promise<{ success: boolean; error?: string }>;
}

export const useCalendarListState = ({
  createCalendar,
  updateCalendar,
  deleteCalendar,
  shareCalendar,
}: UseCalendarListStateProps) => {
  // Modal states
  const [modalState, setModalState] = useState<CalendarModalState>({
    isOpen: false,
    mode: "create",
    calendar: null,
  });

  const [deleteState, setDeleteState] = useState<DeleteState>({
    isOpen: false,
    calendar: null,
    isLoading: false,
  });

  const [isMyCalendarsExpanded, setIsMyCalendarsExpanded] = useState(true);
  const [isSharedCalendarsExpanded, setIsSharedCalendarsExpanded] =
    useState(true);
  const [openMenuUrl, setOpenMenuUrl] = useState<string | null>(null);

  // Modal handlers
  const handleOpenCreateModal = useCallback(() => {
    setModalState({
      isOpen: true,
      mode: "create",
      calendar: null,
    });
  }, []);

  const handleOpenEditModal = useCallback((calendar: CalDavCalendar) => {
    setModalState({
      isOpen: true,
      mode: "edit",
      calendar,
    });
  }, []);

  const handleCloseModal = useCallback(() => {
    setModalState({
      isOpen: false,
      mode: "create",
      calendar: null,
    });
  }, []);

  const handleSaveCalendar = useCallback(
    async (name: string, color: string, description?: string) => {
      if (modalState.mode === "create") {
        const result = await createCalendar({
          displayName: name,
          color,
          description,
          components: ['VEVENT'],
        });
        if (!result.success) {
          throw new Error(result.error);
        }
      } else if (modalState.calendar) {
        const result = await updateCalendar(modalState.calendar.url, {
          displayName: name,
          color,
          description,
        });
        if (!result.success) {
          throw new Error(result.error);
        }
      }
    },
    [modalState, createCalendar, updateCalendar]
  );

  const handleShareCalendar = useCallback(
    async (email: string): Promise<{ success: boolean; error?: string }> => {
      if (!modalState.calendar) {
        return { success: false, error: 'No calendar selected' };
      }
      return shareCalendar(modalState.calendar.url, email);
    },
    [modalState.calendar, shareCalendar]
  );

  // Delete handlers
  const handleOpenDeleteModal = useCallback((calendar: CalDavCalendar) => {
    setDeleteState({
      isOpen: true,
      calendar,
      isLoading: false,
    });
  }, []);

  const handleCloseDeleteModal = useCallback(() => {
    setDeleteState({
      isOpen: false,
      calendar: null,
      isLoading: false,
    });
  }, []);

  const handleConfirmDelete = useCallback(async () => {
    if (!deleteState.calendar) return;

    setDeleteState((prev) => ({ ...prev, isLoading: true }));
    try {
      const result = await deleteCalendar(deleteState.calendar.url);
      if (!result.success) {
        console.error("Failed to delete calendar:", result.error);
      }
      handleCloseDeleteModal();
    } catch (error) {
      console.error("Error deleting calendar:", error);
      setDeleteState((prev) => ({ ...prev, isLoading: false }));
    }
  }, [deleteState.calendar, deleteCalendar, handleCloseDeleteModal]);

  // Menu handlers
  const handleMenuToggle = useCallback(
    (calendarUrl: string, e: React.MouseEvent) => {
      e.stopPropagation();
      setOpenMenuUrl(openMenuUrl === calendarUrl ? null : calendarUrl);
    },
    [openMenuUrl]
  );

  const handleCloseMenu = useCallback(() => {
    setOpenMenuUrl(null);
  }, []);

  // Expansion handlers
  const handleToggleMyCalendars = useCallback(() => {
    setIsMyCalendarsExpanded((prev) => !prev);
  }, []);

  const handleToggleSharedCalendars = useCallback(() => {
    setIsSharedCalendarsExpanded((prev) => !prev);
  }, []);

  return {
    // Modal state
    modalState,
    deleteState,

    // Expansion state
    isMyCalendarsExpanded,
    isSharedCalendarsExpanded,
    openMenuUrl,

    // Modal handlers
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,
    handleShareCalendar,

    // Delete handlers
    handleOpenDeleteModal,
    handleCloseDeleteModal,
    handleConfirmDelete,

    // Menu handlers
    handleMenuToggle,
    handleCloseMenu,

    // Expansion handlers
    handleToggleMyCalendars,
    handleToggleSharedCalendars,
  };
};
