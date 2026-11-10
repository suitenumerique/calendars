import { useCallback, useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { CalendarModal } from "@/features/calendar/components/calendar-list/CalendarModal";
import { DeleteConfirmModal } from "@/features/calendar/components/calendar-list/DeleteConfirmModal";
import { useCalendarDelete } from "@/features/calendar/components/calendar-list/hooks/useCalendarDelete";
import { useCalendarHiding } from "@/features/calendar/components/calendar-list/hooks/useCalendarHiding";
import { useCalendarModal } from "@/features/calendar/components/calendar-list/hooks/useCalendarModal";
import { useMailboxCalendarDelete } from "@/features/calendar/components/calendar-list/hooks/useMailboxCalendarDelete";
import { MailboxCalendarDeleteModal } from "@/features/calendar/components/calendar-list/MailboxCalendarDeleteModal";
import { useCalendarContext } from "@/features/calendar/contexts";
import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";
import {
  isCalendarOwner,
  isMailboxCalendarAdmin,
} from "@/features/calendar/utils/calendar-ownership";
import { sortCalendars } from "@/features/calendar/utils/calendar-order";
import { useMailboxContext } from "@/features/mailbox/MailboxContext";
import { addErrorToast } from "@/features/ui/components/toaster/Toaster";
import { CalendarSettingsHeader } from "./CalendarSettingsHeader";
import { CalendarSettingsSection } from "./CalendarSettingsSection";
import { CalendarSettingsActions } from "./CalendarSettingsActions";

/**
 * Lists the calendars of the user. The user can edit them, and hide or
 * leave the calendars of others.
 */
export const CalendarSettings = () => {
  const { t } = useTranslation();
  const {
    davCalendars,
    hiddenCalendars,
    isLoading,
    setCalendarHidden,
    createCalendar,
    updateCalendar,
    deleteCalendar,
    deleteMailboxCalendar,
  } = useCalendarContext();
  const { availableMailboxes } = useMailboxContext();

  const calendars = useMemo(
    () => sortCalendars([...davCalendars, ...hiddenCalendars]),
    [davCalendars, hiddenCalendars],
  );

  const handleHidingError = useCallback(
    (hidden: boolean) =>
      addErrorToast(t(hidden ? "calendar.list.hideError" : "calendar.list.showAgainError")),
    [t],
  );
  const { setHidden } = useCalendarHiding({ setCalendarHidden, onError: handleHidingError });

  const handleDeleteError = useCallback(
    () => addErrorToast(t("calendar.deleteCalendar.error")),
    [t],
  );
  const mailboxDelete = useMailboxCalendarDelete({
    deleteMailboxCalendar,
    onError: handleDeleteError,
  });
  const calendarDelete = useCalendarDelete({ deleteCalendar, onError: handleDeleteError });

  const { modalState, handleOpenEditModal, handleCloseModal, handleSaveCalendar } =
    useCalendarModal({ createCalendar, updateCalendar });

  const renderActions = (calendar: CalDavCalendar): ReactNode => {
    const isOwner = isCalendarOwner(calendar);
    const isAdmin = isMailboxCalendarAdmin(calendar, availableMailboxes);
    return (
      <CalendarSettingsActions
        calendar={calendar}
        onEdit={handleOpenEditModal}
        onSetHidden={setHidden}
        onDelete={isOwner ? calendarDelete.open : undefined}
        onLeave={isOwner ? undefined : calendarDelete.open}
        onDeleteForMailbox={isAdmin ? mailboxDelete.open : undefined}
      />
    );
  };

  return (
    <div className="calendar-settings">
      <CalendarSettingsHeader />
      <p className="calendar-settings__description">{t("settings.calendars.description")}</p>

      {!(isLoading && calendars.length === 0) && (
        <CalendarSettingsSection
          emptyText={t("settings.calendars.noCalendar")}
          calendars={calendars}
          renderActions={renderActions}
        />
      )}

      <CalendarModal
        isOpen={modalState.isOpen}
        mode={modalState.mode}
        calendar={modalState.calendar}
        onClose={handleCloseModal}
        onSave={(name, color, _mailboxEmail, includeInAvailability) =>
          handleSaveCalendar(name, color, includeInAvailability)
        }
      />

      <DeleteConfirmModal
        calendar={calendarDelete.calendar}
        onConfirm={calendarDelete.confirm}
        onCancel={calendarDelete.close}
        isLoading={calendarDelete.isLoading}
      />

      <MailboxCalendarDeleteModal
        calendar={mailboxDelete.calendar}
        onConfirm={mailboxDelete.confirm}
        onCancel={mailboxDelete.close}
        isLoading={mailboxDelete.isLoading}
      />
    </div>
  );
};
