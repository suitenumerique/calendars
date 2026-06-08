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
import type { CalendarModalState, DeleteState, ShareModalState } from "../types";

interface UseCalendarListStateProps {
  createCalendar: (params: CalDavCalendarCreate) => Promise<{ success: boolean; error?: string }>;
  updateCalendar: (
    url: string,
    options: CalDavCalendarUpdate,
  ) => Promise<{ success: boolean; error?: string }>;
  deleteCalendar: (url: string) => Promise<{ success: boolean; error?: string }>;
}

export const useCalendarListState = ({
  createCalendar,
  updateCalendar,
  deleteCalendar,
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

  const [shareModalState, setShareModalState] = useState<ShareModalState>({
    isOpen: false,
    calendar: null,
  });

  const [isMyCalendarsExpanded, setIsMyCalendarsExpanded] = useState(true);
  const [isSharedCalendarsExpanded, setIsSharedCalendarsExpanded] = useState(true);
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
    async (name: string, color: string, includeInAvailability?: boolean) => {
      if (modalState.mode === "create") {
        // New calendars default to opaque (included in availability).
        // includeInAvailability is only editable after creation.
        const result = await createCalendar({
          displayName: name,
          color,
          components: ["VEVENT"],
        });
        if (!result.success) {
          throw new Error(result.error);
        }
      } else if (modalState.calendar) {
        // Only send props that actually changed: PROPPATCHing every
        // field on every save means a sharee touching just the color
        // also rewrites schedule-calendar-transp on the per-instance
        // row, which has its own bug surface.
        const current = modalState.calendar;
        const params: Parameters<typeof updateCalendar>[1] = {};
        if (name !== current.displayName) {
          params.displayName = name;
        }
        if (color !== current.color) {
          params.color = color;
        }
        if (
          includeInAvailability !== undefined &&
          includeInAvailability !== current.includeInAvailability
        ) {
          params.includeInAvailability = includeInAvailability;
        }
        if (Object.keys(params).length === 0) {
          return;
        }
        const result = await updateCalendar(modalState.calendar.url, params);
        if (!result.success) {
          throw new Error(result.error);
        }
      }
    },
    [modalState, createCalendar, updateCalendar],
  );

  // Share modal handlers
  const handleOpenShareModal = useCallback((calendar: CalDavCalendar) => {
    setShareModalState({ isOpen: true, calendar });
  }, []);

  const handleCloseShareModal = useCallback(() => {
    setShareModalState({ isOpen: false, calendar: null });
  }, []);

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
    (calendarUrl: string) => {
      setOpenMenuUrl(openMenuUrl === calendarUrl ? null : calendarUrl);
    },
    [openMenuUrl],
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
    shareModalState,

    // Expansion state
    isMyCalendarsExpanded,
    isSharedCalendarsExpanded,
    openMenuUrl,

    // Modal handlers
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,

    // Share modal handlers
    handleOpenShareModal,
    handleCloseShareModal,

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
