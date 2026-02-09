/**
 * CalendarList component - List of calendars with visibility toggles.
 */

import { useState, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import type { Calendar } from "../../types";
import { useCalendarContext } from "../../contexts";

import { CalendarModal } from "./CalendarModal";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import { ImportEventsModal } from "./ImportEventsModal";
import { SubscriptionUrlModal } from "./SubscriptionUrlModal";
import { CalendarListItem, SharedCalendarListItem } from "./CalendarListItem";
import { useCalendarListState } from "./hooks/useCalendarListState";
import type { CalendarListProps } from "./types";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import { Calendar as DjangoCalendar, getCalendars } from "../../api";

export const CalendarList = ({ calendars }: CalendarListProps) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
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
    isSharedCalendarsExpanded,
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
    handleToggleSharedCalendars,
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
    try {
      // Extract the CalDAV path from the calendar URL
      // URL format: http://localhost:8921/api/v1.0/caldav/calendars/user@example.com/uuid/
      const url = new URL(davCalendar.url);
      const pathParts = url.pathname.split("/").filter(Boolean);

      // Find the index of "calendars" and extract from there
      const calendarsIndex = pathParts.findIndex((part) => part === "calendars");

      if (calendarsIndex === -1) {
        console.error("Invalid calendar URL format - 'calendars' segment not found:", davCalendar.url);
        // Reset modal state to avoid stale data
        setSubscriptionModal({ isOpen: false, calendarName: "", caldavPath: null });
        return;
      }

      // Validate that we have enough parts for a valid path: calendars/email/uuid
      const remainingParts = pathParts.slice(calendarsIndex);
      if (remainingParts.length < 3) {
        console.error("Invalid calendar URL format - incomplete path:", davCalendar.url);
        // Reset modal state to avoid stale data
        setSubscriptionModal({ isOpen: false, calendarName: "", caldavPath: null });
        return;
      }

      // Ensure trailing slash for consistency with backend expectations
      const caldavPath = "/" + remainingParts.join("/") + "/";

      setSubscriptionModal({
        isOpen: true,
        calendarName: davCalendar.displayName || "",
        caldavPath: caldavPath,
      });
    } catch (error) {
      console.error("Failed to parse calendar URL:", error);
      // Reset modal state on error
      setSubscriptionModal({ isOpen: false, calendarName: "", caldavPath: null });
    }
  };

  const handleCloseSubscriptionModal = () => {
    setSubscriptionModal({ isOpen: false, calendarName: "", caldavPath: null });
  };

  // Ensure calendars is an array
  const calendarsArray = Array.isArray(calendars) ? calendars : [];

  // Import modal state
  const [importModal, setImportModal] = useState<{
    isOpen: boolean;
    calendarId: string | null;
    calendarName: string;
  }>({ isOpen: false, calendarId: null, calendarName: "" });

  const handleOpenImportModal = async (davCalendar: CalDavCalendar) => {
    try {
      // Extract the CalDAV path from the calendar URL
      const url = new URL(davCalendar.url);
      const pathParts = url.pathname.split("/").filter(Boolean);
      const calendarsIndex = pathParts.findIndex((part) => part === "calendars");

      if (calendarsIndex === -1 || pathParts.slice(calendarsIndex).length < 3) {
        console.error("Invalid calendar URL format:", davCalendar.url);
        return;
      }

      const caldavPath = "/" + pathParts.slice(calendarsIndex).join("/") + "/";

      // Find the matching Django Calendar by caldav_path
      const caldavApiRoot = "/api/v1.0/caldav";
      const normalize = (p: string) =>
        decodeURIComponent(p).replace(caldavApiRoot, "").replace(/\/+$/, "");

      const findCalendar = (cals: DjangoCalendar[]) =>
        cals.find((cal) => normalize(cal.caldav_path) === normalize(caldavPath));

      // Fetch fresh Django calendars to ensure newly created calendars are included.
      // Uses React Query cache, forcing a refetch if stale.
      const freshCalendars = await queryClient.fetchQuery({
        queryKey: ["calendars"],
        queryFn: getCalendars,
      });
      const djangoCalendar = findCalendar(freshCalendars);

      if (!djangoCalendar) {
        console.error("No matching Django calendar found for path:", caldavPath);
        return;
      }

      setImportModal({
        isOpen: true,
        calendarId: djangoCalendar.id,
        calendarName: davCalendar.displayName || "",
      });
    } catch (error) {
      console.error("Failed to parse calendar URL:", error);
    }
  };

  const handleCloseImportModal = () => {
    setImportModal({ isOpen: false, calendarId: null, calendarName: "" });
  };

  const handleImportSuccess = useCallback(() => {
    if (calendarRef.current) {
      calendarRef.current.refetchEvents();
    }
  }, [calendarRef]);

  // Use translation key for shared marker
  const sharedMarker = t('calendar.list.shared');

  // Memoize filtered calendars to avoid recalculation on every render
  const sharedCalendars = useMemo(
    () => calendarsArray.filter((cal) => cal.name.includes(sharedMarker)),
    [calendarsArray, sharedMarker]
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
                {sharedCalendars.map((calendar: Calendar) => (
                  <SharedCalendarListItem
                    key={calendar.id}
                    calendar={calendar}
                    isVisible={visibleCalendarUrls.has(String(calendar.id))}
                    onToggleVisibility={toggleCalendarVisibility}
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

      {importModal.isOpen && importModal.calendarId && (
        <ImportEventsModal
          isOpen={importModal.isOpen}
          calendarId={importModal.calendarId}
          calendarName={importModal.calendarName}
          onClose={handleCloseImportModal}
          onImportSuccess={handleImportSuccess}
        />
      )}
    </>
  );
};
