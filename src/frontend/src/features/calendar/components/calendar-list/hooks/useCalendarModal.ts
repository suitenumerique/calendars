import { useState, useCallback } from "react";

import type {
  CalDavCalendar,
  CalDavCalendarCreate,
  CalDavCalendarUpdate,
} from "../../../services/dav/types/caldav-service";
import type { CalendarModalState } from "../types";

interface UseCalendarModalProps {
  createCalendar: (params: CalDavCalendarCreate) => Promise<{ success: boolean; error?: string }>;
  updateCalendar: (
    url: string,
    options: CalDavCalendarUpdate,
  ) => Promise<{ success: boolean; error?: string }>;
}

/**
 * Manages the state of the dialog that creates or edits a calendar. On
 * edit, the save sends only the changed properties. The save throws when
 * it fails. The caller closes the dialog.
 */
export const useCalendarModal = ({ createCalendar, updateCalendar }: UseCalendarModalProps) => {
  const [modalState, setModalState] = useState<CalendarModalState>({
    isOpen: false,
    mode: "create",
    calendar: null,
  });

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

  return {
    modalState,
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,
  };
};
