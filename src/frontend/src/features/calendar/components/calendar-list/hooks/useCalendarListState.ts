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
import type { ShareModalState } from "../types";
import { useCalendarModal } from "./useCalendarModal";

interface UseCalendarListStateProps {
  createCalendar: (params: CalDavCalendarCreate) => Promise<{ success: boolean; error?: string }>;
  updateCalendar: (
    url: string,
    options: CalDavCalendarUpdate,
  ) => Promise<{ success: boolean; error?: string }>;
}

export const useCalendarListState = ({
  createCalendar,
  updateCalendar,
}: UseCalendarListStateProps) => {
  const {
    modalState,
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,
  } = useCalendarModal({ createCalendar, updateCalendar });

  const [shareModalState, setShareModalState] = useState<ShareModalState>({
    isOpen: false,
    calendar: null,
  });

  const [isExpanded, setIsExpanded] = useState(true);
  const [openMenuUrl, setOpenMenuUrl] = useState<string | null>(null);

  // Share modal handlers
  const handleOpenShareModal = useCallback((calendar: CalDavCalendar) => {
    setShareModalState({ isOpen: true, calendar });
  }, []);

  const handleCloseShareModal = useCallback(() => {
    setShareModalState({ isOpen: false, calendar: null });
  }, []);

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

  const handleToggleExpanded = useCallback(() => {
    setIsExpanded((prev) => !prev);
  }, []);

  return {
    // Modal state
    modalState,
    shareModalState,

    // Expansion state
    isExpanded,
    openMenuUrl,

    // Modal handlers
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,

    // Share modal handlers
    handleOpenShareModal,
    handleCloseShareModal,

    // Menu handlers
    handleMenuToggle,
    handleCloseMenu,

    // Expansion handler
    handleToggleExpanded,
  };
};
