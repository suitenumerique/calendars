/**
 * CalendarList component - List of calendars with visibility toggles.
 */

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";

import { useCalendarContext } from "../../contexts";

import { CalendarModal } from "./CalendarModal";
import { CalendarShareModal } from "./CalendarShareModal";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import { ImportEventsModal } from "./ImportEventsModal";
import { SubscriptionUrlModal } from "./SubscriptionUrlModal";
import { CalendarListItem } from "./CalendarListItem";
import { useCalendarListState } from "./hooks/useCalendarListState";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import { extractCaldavPath } from "./utils";

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
    calendarRef,
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
              <span
                className={`material-icons calendar-list__toggle-icon ${
                  isMyCalendarsExpanded
                    ? 'calendar-list__toggle-icon--expanded'
                    : ''
                }`}
              >
                expand_more
              </span>
              <span className="calendar-list__section-title">
                {t('calendar.list.myCalendars')}
              </span>
            </button>
            <button
              className="calendar-list__add-btn"
              onClick={handleOpenCreateModal}
              title={t('calendar.createCalendar.title')}
            >
              <span className="material-icons">add</span>
            </button>
          </div>
          {isMyCalendarsExpanded && (
            <div className="calendar-list__items">
              {ownedCalendars.map((calendar) => (
                <CalendarListItem
                  key={calendar.url}
                  calendar={calendar}
                  isVisible={visibleCalendarUrls.has(calendar.url)}
                  isMenuOpen={openMenuUrl === calendar.url}
                  onToggleVisibility={toggleCalendarVisibility}
                  onMenuToggle={handleMenuToggle}
                  onEdit={handleOpenEditModal}
                  onDelete={handleOpenDeleteModal}
                  onShare={handleOpenShareModal}
                  onImport={handleOpenImportModal}
                  onSubscription={handleOpenSubscriptionModal}
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
                <span
                  className={`material-icons calendar-list__toggle-icon ${
                    isSharedCalendarsExpanded
                      ? 'calendar-list__toggle-icon--expanded'
                      : ''
                  }`}
                >
                  expand_more
                </span>
                <span className="calendar-list__section-title">
                  {t('calendar.list.sharedCalendars')}
                </span>
              </button>
            </div>
            {isSharedCalendarsExpanded && (
              <div className="calendar-list__items">
                {sharedCalendars.map((calendar) => (
                  <CalendarListItem
                    key={calendar.url}
                    calendar={calendar}
                    isVisible={visibleCalendarUrls.has(calendar.url)}
                    isMenuOpen={openMenuUrl === calendar.url}
                    onToggleVisibility={toggleCalendarVisibility}
                    onMenuToggle={handleMenuToggle}
                    onEdit={handleOpenEditModal}
                    onDelete={handleOpenDeleteModal}
                    onImport={handleOpenImportModal}
                    onSubscription={handleOpenSubscriptionModal}
                    onCloseMenu={handleCloseMenu}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <CalendarModal
        isOpen={modalState.isOpen}
        mode={modalState.mode}
        calendar={modalState.calendar}
        onClose={handleCloseModal}
        onSave={handleSaveCalendar}
      />

      <CalendarShareModal
        isOpen={shareModalState.isOpen}
        calendar={shareModalState.calendar}
        onClose={handleCloseShareModal}
      />

      <DeleteConfirmModal
        isOpen={deleteState.isOpen}
        calendarName={deleteState.calendar?.displayName || ''}
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
