import { useState, useCallback } from "react";

import type { CalendarContextType } from "../../../contexts/CalendarContext";
import type { CalDavCalendar } from "../../../services/dav/types/caldav-service";
import type { ShareModalState } from "../types";
import { useCalendarModal } from "./useCalendarModal";

interface UseCalendarListStateProps {
  createCalendar: CalendarContextType["createCalendar"];
  updateCalendar: CalendarContextType["updateCalendar"];
}

/** Holds the edit modal, the share modal and the open menu of the sidebar list. */
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

  return {
    // Modal state
    modalState,
    shareModalState,
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
  };
};
