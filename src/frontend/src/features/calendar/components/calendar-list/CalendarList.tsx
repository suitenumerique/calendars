/**
 * CalendarList component - List of calendars with visibility toggles.
 * It prompts users without a calendar of their own to create one. Users
 * with shared or hidden calendars can dismiss the prompt. Users with no
 * calendar must create one.
 */

import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCalendarContext } from "../../contexts";
import { setupCalendar } from "@/features/mailbox/api";
import { useMailboxContext } from "@/features/mailbox/MailboxContext";
import {
  getCalendarGroup,
  isMailboxCalendarAdmin,
} from "@/features/calendar/utils/calendar-ownership";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import { CalendarModal } from "./CalendarModal";
import { CalendarShareModal } from "./CalendarShareModal";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import { MailboxCalendarDeleteModal } from "./MailboxCalendarDeleteModal";
import { ImportEventsModal } from "./ImportEventsModal";
import { SubscriptionUrlModal } from "./SubscriptionUrlModal";
import { CalendarListItem } from "./CalendarListItem";
import { CalendarHiddenToast } from "./CalendarHiddenToast";
import { useCalendarDelete } from "./hooks/useCalendarDelete";
import { useCalendarHiding } from "./hooks/useCalendarHiding";
import { useCalendarListState } from "./hooks/useCalendarListState";
import { useMailboxCalendarDelete } from "./hooks/useMailboxCalendarDelete";
import { extractCaldavPath, loadOnboardingDismissed, saveOnboardingDismissed } from "./utils";
import { Plus } from "@gouvfr-lasuite/ui-components/icons";

import type { CalDavCalendar } from "../../services/dav/types/caldav-service";

export const CalendarList = () => {
  const { t } = useTranslation();
  const {
    orderedCalendars,
    hiddenCalendars,
    visibleCalendarUrls,
    toggleCalendarVisibility,
    createCalendar,
    updateCalendar,
    deleteCalendar,
    deleteMailboxCalendar,
    moveCalendar,
    setCalendarHidden,
    refreshCalendars,
    calendarRef,
    isLoading: isCalendarLoading,
  } = useCalendarContext();

  const handleDeleteError = useCallback(() => {
    addToast(
      <ToasterItem type="error" closeButton>
        {t("calendar.deleteCalendar.error")}
      </ToasterItem>,
    );
  }, [t]);

  const {
    modalState,
    shareModalState,
    openMenuUrl,
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,
    handleOpenShareModal,
    handleCloseShareModal,
    handleMenuToggle,
    handleCloseMenu,
  } = useCalendarListState({ createCalendar, updateCalendar });

  const calendarDelete = useCalendarDelete({ deleteCalendar, onError: handleDeleteError });

  const { availableMailboxes } = useMailboxContext();
  const mailboxDelete = useMailboxCalendarDelete({
    deleteMailboxCalendar,
    onError: handleDeleteError,
  });

  const handleHidingError = useCallback(
    (hidden: boolean) => {
      addToast(
        <ToasterItem type="error" closeButton>
          {t(hidden ? "calendar.list.hideError" : "calendar.list.showAgainError")}
        </ToasterItem>,
      );
    },
    [t],
  );
  const { hide: hideCalendar, show: showCalendar } = useCalendarHiding({
    setCalendarHidden,
    onError: handleHidingError,
  });
  const handleHide = useCallback(
    (calendar: CalDavCalendar) => {
      void hideCalendar(calendar).then((hidden) => {
        if (!hidden) return;
        addToast(<CalendarHiddenToast onUndo={() => void showCalendar(calendar)} />);
      });
    },
    [hideCalendar, showCalendar],
  );

  const [isOnboardingDismissed, setIsOnboardingDismissed] = useState(loadOnboardingDismissed);
  const dismissOnboarding = () => {
    setIsOnboardingDismissed(true);
    saveOnboardingDismissed();
  };
  // A hidden calendar is a calendar that the user can show again.
  const canDismissOnboarding = orderedCalendars.length > 0 || hiddenCalendars.length > 0;
  // The user acts for a mailbox calendar as for an own one.
  const isUsersCalendar = (calendar: CalDavCalendar) => getCalendarGroup(calendar) !== "shared";
  const showOnboarding =
    !isCalendarLoading &&
    !orderedCalendars.some(isUsersCalendar) &&
    (!canDismissOnboarding || !isOnboardingDismissed);

  // Wrap save to handle mailbox calendar creation
  const handleSaveWithMailbox = useCallback(
    async (name: string, color: string, mailboxEmail?: string, includeInAvailability?: boolean) => {
      if (mailboxEmail) {
        await setupCalendar(name, mailboxEmail, color);
        await refreshCalendars();
      } else {
        await handleSaveCalendar(name, color, includeInAvailability);
      }
    },
    [handleSaveCalendar, refreshCalendars],
  );

  // Subscription modal state
  const [subscriptionModal, setSubscriptionModal] = useState<{
    isOpen: boolean;
    calendarName: string;
    caldavPath: string | null;
  }>({ isOpen: false, calendarName: "", caldavPath: null });

  const handleOpenSubscriptionModal = (davCalendar: CalDavCalendar) => {
    const caldavPath = extractCaldavPath(davCalendar.url);
    if (!caldavPath) {
      return;
    }
    setSubscriptionModal({
      isOpen: true,
      calendarName: davCalendar.displayName || "",
      caldavPath,
    });
  };

  const handleCloseSubscriptionModal = () => {
    setSubscriptionModal({ isOpen: false, calendarName: "", caldavPath: null });
  };

  // Import modal state
  const [importModal, setImportModal] = useState<{
    isOpen: boolean;
    caldavPath: string | null;
    calendarName: string;
  }>({ isOpen: false, caldavPath: null, calendarName: "" });

  const handleOpenImportModal = (davCalendar: CalDavCalendar) => {
    const caldavPath = extractCaldavPath(davCalendar.url);
    if (!caldavPath) {
      return;
    }
    setImportModal({
      isOpen: true,
      caldavPath,
      calendarName: davCalendar.displayName || "",
    });
  };

  const handleCloseImportModal = () => {
    setImportModal({ isOpen: false, caldavPath: null, calendarName: "" });
  };

  const handleImportSuccess = useCallback(() => {
    if (calendarRef.current) {
      calendarRef.current.refetchEvents();
    }
  }, [calendarRef]);

  const handleMove = useCallback(
    (calendar: CalDavCalendar, direction: "up" | "down") => {
      // The error text is not translated, so log it and show a translated toast.
      void moveCalendar(calendar.url, direction).then((result) => {
        if (!result.success) {
          console.error("Failed to move calendar:", result.error);
          addToast(
            <ToasterItem type="error" closeButton>
              {t("calendar.error.reorderCalendars")}
            </ToasterItem>,
          );
        }
      });
    },
    [moveCalendar, t],
  );

  const handleMoveUp = useCallback(
    (calendar: CalDavCalendar) => handleMove(calendar, "up"),
    [handleMove],
  );

  const handleMoveDown = useCallback(
    (calendar: CalDavCalendar) => handleMove(calendar, "down"),
    [handleMove],
  );

  return (
    <>
      <div className="calendar-list">
        <div className="calendar-list__section">
          <div className="calendar-list__section-header">
            <span className="calendar-list__section-title">{t("calendar.list.title")}</span>
            <button
              className="calendar-list__add-btn"
              onClick={handleOpenCreateModal}
              title={t("calendar.createCalendar.title")}
              aria-label={t("calendar.createCalendar.title")}
            >
              <Plus />
            </button>
          </div>
          <div className="calendar-list__items">
            {orderedCalendars.map((calendar, idx) => (
              <CalendarListItem
                key={calendar.url}
                calendar={calendar}
                isVisible={visibleCalendarUrls.has(calendar.url)}
                isMenuOpen={openMenuUrl === calendar.url}
                onToggleVisibility={toggleCalendarVisibility}
                onMenuToggle={handleMenuToggle}
                onEdit={handleOpenEditModal}
                onDelete={calendarDelete.open}
                onDeleteForMailbox={
                  isMailboxCalendarAdmin(calendar, availableMailboxes)
                    ? mailboxDelete.open
                    : undefined
                }
                onHide={handleHide}
                onShare={isUsersCalendar(calendar) ? handleOpenShareModal : undefined}
                onImport={handleOpenImportModal}
                onSubscription={handleOpenSubscriptionModal}
                onMoveUp={idx > 0 ? handleMoveUp : undefined}
                onMoveDown={idx < orderedCalendars.length - 1 ? handleMoveDown : undefined}
                onCloseMenu={handleCloseMenu}
              />
            ))}
          </div>
        </div>
      </div>

      <CalendarModal
        isOpen={showOnboarding}
        mode="create"
        onClose={dismissOnboarding}
        onSave={handleSaveWithMailbox}
        isOnboarding
        canDismissOnboarding={canDismissOnboarding}
      />

      {/* Normal create/edit modal */}
      <CalendarModal
        isOpen={modalState.isOpen}
        mode={modalState.mode}
        calendar={modalState.calendar}
        onClose={handleCloseModal}
        onSave={handleSaveWithMailbox}
      />

      <CalendarShareModal
        isOpen={shareModalState.isOpen}
        calendar={shareModalState.calendar}
        onClose={handleCloseShareModal}
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

      {subscriptionModal.isOpen && subscriptionModal.caldavPath && (
        <SubscriptionUrlModal
          isOpen={subscriptionModal.isOpen}
          caldavPath={subscriptionModal.caldavPath}
          calendarName={subscriptionModal.calendarName}
          onClose={handleCloseSubscriptionModal}
        />
      )}

      {importModal.isOpen && importModal.caldavPath && (
        <ImportEventsModal
          isOpen={importModal.isOpen}
          caldavPath={importModal.caldavPath}
          calendarName={importModal.calendarName}
          onClose={handleCloseImportModal}
          onImportSuccess={handleImportSuccess}
        />
      )}
    </>
  );
};
