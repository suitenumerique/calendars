/**
 * CalendarList component - List of calendars with visibility toggles.
 */

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";

import { useCalendarContext } from "../../contexts";

import { CalendarModal } from "./CalendarModal";
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
    davCalendars,
    visibleCalendarUrls,
    toggleCalendarVisibility,
    createCalendar,
    updateCalendar,
    deleteCalendar,
    shareCalendar,
    calendarRef,
  } = useCalendarContext();

  const {
    modalState,
    deleteState,
    isMyCalendarsExpanded,
    openMenuUrl,
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseModal,
    handleSaveCalendar,
    handleShareCalendar,
    handleOpenDeleteModal,
    handleCloseDeleteModal,
    handleConfirmDelete,
    handleMenuToggle,
    handleCloseMenu,
    handleToggleMyCalendars,
  } = useCalendarListState({
    createCalendar,
    updateCalendar,
    deleteCalendar,
    shareCalendar,
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
              {davCalendars.map((calendar) => (
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
      </div>

      <CalendarModal
        isOpen={modalState.isOpen}
        mode={modalState.mode}
        calendar={modalState.calendar}
        onClose={handleCloseModal}
        onSave={handleSaveCalendar}
        onShare={handleShareCalendar}
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
