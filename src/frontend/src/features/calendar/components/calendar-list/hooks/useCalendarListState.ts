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
import type { DeleteState, ShareModalState } from "../types";
import { useCalendarModal } from "./useCalendarModal";

interface UseCalendarListStateProps {
  createCalendar: (params: CalDavCalendarCreate) => Promise<{ success: boolean; error?: string }>;
  updateCalendar: (
    url: string,
    options: CalDavCalendarUpdate,
  ) => Promise<{ success: boolean; error?: string }>;
  deleteCalendar: (url: string) => Promise<{ success: boolean; error?: string }>;
  onDeleteError: () => void;
}

export const useCalendarListState = ({
  createCalendar,
  updateCalendar,
  deleteCalendar,
  onDeleteError,
}: UseCalendarListStateProps) => {
  const {
    modalState,
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,
  } = useCalendarModal({ createCalendar, updateCalendar });

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
    const result = await deleteCalendar(deleteState.calendar.url);
    handleCloseDeleteModal();
    if (!result.success) {
      console.error("Failed to delete calendar:", result.error);
      onDeleteError();
    }
  }, [deleteState.calendar, deleteCalendar, handleCloseDeleteModal, onDeleteError]);

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
