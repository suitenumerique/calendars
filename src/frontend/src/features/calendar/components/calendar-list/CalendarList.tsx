/**
 * CalendarList component - List of calendars with visibility toggles.
 * Shows onboarding modal when user has no calendars.
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
import { extractCaldavPath } from "./utils";
import { Plus, ChevronDown } from "@gouvfr-lasuite/ui-kit/icons";

import type { CalDavCalendar } from "../../services/dav/types/caldav-service";

export const CalendarList = () => {
  const { t } = useTranslation();
  const {
    ownedCalendars,
    sharedCalendars,
    davCalendars,
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

  // Onboarding: show modal when user has no calendars at all
  const showOnboarding = !isCalendarLoading && davCalendars.length === 0;

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

  const handleMoveUp = useCallback(
    (calendar: CalDavCalendar) => {
      // moveCalendar resolves with `{success: false, error}` when any
      // PROPPATCH fails — surface that to the user instead of swallowing
      // it (and instead of leaving the visible state quietly stale).
      void moveCalendar(calendar.url, "up").then((result) => {
        if (!result.success) {
          addToast(
            <ToasterItem type="error" closeButton>
              {result.error || t("calendar.error.fetchCalendars")}
            </ToasterItem>,
          );
        }
      });
    },
    [moveCalendar, t],
  );

  const handleMoveDown = useCallback(
    (calendar: CalDavCalendar) => {
      void moveCalendar(calendar.url, "down").then((result) => {
        if (!result.success) {
          addToast(
            <ToasterItem type="error" closeButton>
              {result.error || t("calendar.error.fetchCalendars")}
            </ToasterItem>,
          );
        }
      });
    },
    [moveCalendar, t],
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

      {/* Onboarding modal: shown when user has no calendars */}
      <CalendarModal
        isOpen={showOnboarding}
        mode="create"
        onClose={() => {}}
        onSave={handleSaveWithMailbox}
        isOnboarding
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
        calendarName={deleteState.calendar?.displayName || ""}
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
