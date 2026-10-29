/**
 * CalendarList component - List of calendars with visibility toggles.
 * It prompts users without an owned calendar to create one. Users
 * with shared calendars can dismiss the prompt. Users with no
 * calendar must create one.
 */

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useCalendarContext } from "../../contexts";
import { setupCalendar } from "@/features/mailbox/api";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import { CalendarModal } from "./CalendarModal";
import { CalendarShareModal } from "./CalendarShareModal";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import { ImportEventsModal } from "./ImportEventsModal";
import { SubscriptionUrlModal } from "./SubscriptionUrlModal";
import { CalendarListItem } from "./CalendarListItem";
import { useCalendarListState } from "./hooks/useCalendarListState";
import { extractCaldavPath, loadOnboardingDismissed, saveOnboardingDismissed } from "./utils";
import { Plus, ChevronDown } from "@gouvfr-lasuite/ui-components/icons";

import type { CalDavCalendar } from "../../services/dav/types/caldav-service";

export const CalendarList = () => {
  const { t } = useTranslation();
  const {
    ownedCalendars,
    sharedCalendars,
    visibleCalendarUrls,
    toggleCalendarVisibility,
    createCalendar,
    updateCalendar,
    deleteCalendar,
    moveCalendar,
    refreshCalendars,
    calendarRef,
    isLoading: isCalendarLoading,
  } = useCalendarContext();

  const {
    modalState,
    deleteState,
    shareModalState,
    isMyCalendarsExpanded,
    isSharedCalendarsExpanded,
    openMenuUrl,
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,
    handleOpenShareModal,
    handleCloseShareModal,
    handleOpenDeleteModal,
    handleCloseDeleteModal,
    handleConfirmDelete,
    handleMenuToggle,
    handleCloseMenu,
    handleToggleMyCalendars,
    handleToggleSharedCalendars,
  } = useCalendarListState({
    createCalendar,
    updateCalendar,
    deleteCalendar,
  });

  const [isOnboardingDismissed, setIsOnboardingDismissed] = useState(loadOnboardingDismissed);
  const dismissOnboarding = () => {
    setIsOnboardingDismissed(true);
    saveOnboardingDismissed();
  };
  const canDismissOnboarding = sharedCalendars.length > 0;
  const showOnboarding =
    !isCalendarLoading &&
    ownedCalendars.length === 0 &&
    (sharedCalendars.length === 0 || !isOnboardingDismissed);

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
            <button
              className="calendar-list__toggle-btn"
              onClick={handleToggleMyCalendars}
              aria-expanded={isMyCalendarsExpanded}
            >
              <ChevronDown
                className={`calendar-list__toggle-icon ${
                  isMyCalendarsExpanded ? "calendar-list__toggle-icon--expanded" : ""
                }`}
              />
              <span className="calendar-list__section-title">{t("calendar.list.myCalendars")}</span>
            </button>
            <button
              className="calendar-list__add-btn"
              onClick={handleOpenCreateModal}
              title={t("calendar.createCalendar.title")}
              aria-label={t("calendar.createCalendar.title")}
            >
              <Plus />
            </button>
          </div>
          {isMyCalendarsExpanded && (
            <div className="calendar-list__items">
              {ownedCalendars.map((calendar, idx) => (
                <CalendarListItem
                  key={calendar.url}
                  calendar={calendar}
                  isVisible={visibleCalendarUrls.has(calendar.url)}
                  isMenuOpen={openMenuUrl === calendar.url}
                  mailboxEmail={calendar.mailboxEmail}
                  onToggleVisibility={toggleCalendarVisibility}
                  onMenuToggle={handleMenuToggle}
                  onEdit={handleOpenEditModal}
                  onDelete={handleOpenDeleteModal}
                  onShare={handleOpenShareModal}
                  onImport={handleOpenImportModal}
                  onSubscription={handleOpenSubscriptionModal}
                  onMoveUp={idx > 0 ? handleMoveUp : undefined}
                  onMoveDown={idx < ownedCalendars.length - 1 ? handleMoveDown : undefined}
                  onCloseMenu={handleCloseMenu}
                />
              ))}
            </div>
          )}
        </div>

        {sharedCalendars.length > 0 && (
          <div className="calendar-list__section">
            <div className="calendar-list__section-header">
              <button
                className="calendar-list__toggle-btn"
                onClick={handleToggleSharedCalendars}
                aria-expanded={isSharedCalendarsExpanded}
              >
                <ChevronDown
                  className={`calendar-list__toggle-icon ${
                    isSharedCalendarsExpanded ? "calendar-list__toggle-icon--expanded" : ""
                  }`}
                />
                <span className="calendar-list__section-title">
                  {t("calendar.list.sharedCalendars")}
                </span>
              </button>
            </div>
            {isSharedCalendarsExpanded && (
              <div className="calendar-list__items">
                {sharedCalendars.map((calendar, idx) => (
                  <CalendarListItem
                    key={calendar.url}
                    calendar={calendar}
                    isVisible={visibleCalendarUrls.has(calendar.url)}
                    isMenuOpen={openMenuUrl === calendar.url}
                    mailboxEmail={calendar.mailboxEmail}
                    onToggleVisibility={toggleCalendarVisibility}
                    onMenuToggle={handleMenuToggle}
                    onEdit={handleOpenEditModal}
                    onDelete={handleOpenDeleteModal}
                    onImport={handleOpenImportModal}
                    onSubscription={handleOpenSubscriptionModal}
                    onMoveUp={idx > 0 ? handleMoveUp : undefined}
                    onMoveDown={idx < sharedCalendars.length - 1 ? handleMoveDown : undefined}
                    onCloseMenu={handleCloseMenu}
                  />
                ))}
              </div>
            )}
          </div>
        )}
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
        isOpen={deleteState.isOpen}
        calendar={deleteState.calendar}
        onConfirm={handleConfirmDelete}
        onCancel={handleCloseDeleteModal}
        isLoading={deleteState.isLoading}
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
