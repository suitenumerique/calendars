/**
 * CalendarList component - List of calendars with visibility toggles.
 * Shows onboarding modal when user has no calendars.
 */

import { useState, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useCalendarContext } from "../../contexts";
import { setupCalendar } from "@/features/mailbox/api";
import {
  useSubscriptions,
  useDeleteSubscription,
  useReactivateSubscription,
} from "../../hooks/useCalendars";

import { CalendarModal } from "./CalendarModal";
import { CalendarShareModal } from "./CalendarShareModal";
import { DeleteConfirmModal } from "./DeleteConfirmModal";
import { ImportEventsModal } from "./ImportEventsModal";
import { SubscriptionUrlModal } from "./SubscriptionUrlModal";
import { SubscriptionCalendarSection } from "./SubscriptionCalendarSection";
import { CalendarListItem } from "./CalendarListItem";
import { useCalendarListState } from "./hooks/useCalendarListState";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";
import type { Subscription } from "../../api";
import { extractCaldavPath } from "./utils";

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

  const handleSubscriptionRefresh = useCallback(async () => {
    await refreshCalendars();
    if (calendarRef.current) {
      calendarRef.current.refetchEvents();
    }
  }, [refreshCalendars, calendarRef]);

  // Subscriptions — shared SabreDAV-backed ICS calendars
  const { data: subscriptions = [] } = useSubscriptions();
  const deleteSubMutation = useDeleteSubscription();
  const reactivateSubMutation = useReactivateSubscription();

  // Separate subscription calendars from owned/shared calendars.
  // Subscription calendars surface in PROPFIND with ownerType="SUBSCRIPTION".
  const [deletingPaths, setDeletingPaths] = useState<Set<string>>(new Set());

  const { regularCalendars, subscriptionCalendars } = useMemo(() => {
    const regular: CalDavCalendar[] = [];
    const subscription: CalDavCalendar[] = [];
    for (const cal of ownedCalendars) {
      const calPath = extractCaldavPath(cal.url);
      if (calPath && deletingPaths.has(calPath)) continue;
      if (cal.ownerType === "SUBSCRIPTION") {
        subscription.push(cal);
      } else {
        regular.push(cal);
      }
    }
    // Sort by subscription created_at (oldest first).
    subscription.sort((a, b) => {
      const pathA = extractCaldavPath(a.url);
      const pathB = extractCaldavPath(b.url);
      const sA = subscriptions.find(
        (s) => extractCaldavPath(s.caldav_path) === pathA,
      );
      const sB = subscriptions.find(
        (s) => extractCaldavPath(s.caldav_path) === pathB,
      );
      if (!sA?.created_at || !sB?.created_at) return 0;
      return (
        new Date(sA.created_at).getTime() - new Date(sB.created_at).getTime()
      );
    });
    return { regularCalendars: regular, subscriptionCalendars: subscription };
  }, [ownedCalendars, subscriptions, deletingPaths]);

  const handleDeleteSubscription = useCallback(
    async (subscription: Subscription) => {
      setDeletingPaths((prev) => new Set(prev).add(subscription.caldav_path));
      try {
        await deleteSubMutation.mutateAsync(subscription.subscription_id);
        await refreshCalendars();
      } finally {
        setDeletingPaths((prev) => {
          const next = new Set(prev);
          next.delete(subscription.caldav_path);
          return next;
        });
      }
    },
    [deleteSubMutation, refreshCalendars],
  );

  const handleReactivateSubscription = useCallback(
    async (subscription: Subscription) => {
      await reactivateSubMutation.mutateAsync(subscription.subscription_id);
    },
    [reactivateSubMutation],
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
                    ? "calendar-list__toggle-icon--expanded"
                    : ""
                }`}
              >
                expand_more
              </span>
              <span className="calendar-list__section-title">
                {t("calendar.list.myCalendars")}
              </span>
            </button>
            <button
              className="calendar-list__add-btn"
              onClick={handleOpenCreateModal}
              title={t("calendar.createCalendar.title")}
            >
              <span className="material-icons">add</span>
            </button>
          </div>
          {isMyCalendarsExpanded && (
            <div className="calendar-list__items">
              {regularCalendars.map((calendar) => (
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
                  onCloseMenu={handleCloseMenu}
                />
              ))}
            </div>
          )}
        </div>

        <SubscriptionCalendarSection
          calendars={subscriptionCalendars}
          subscriptions={subscriptions}
          visibleCalendarUrls={visibleCalendarUrls}
          onToggleVisibility={toggleCalendarVisibility}
          onDelete={handleDeleteSubscription}
          onReactivate={handleReactivateSubscription}
          onEdit={handleOpenEditModal}
          onRefresh={handleSubscriptionRefresh}
        />

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
                      ? "calendar-list__toggle-icon--expanded"
                      : ""
                  }`}
                >
                  expand_more
                </span>
                <span className="calendar-list__section-title">
                  {t("calendar.list.sharedCalendars")}
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
                    mailboxEmail={calendar.mailboxEmail}
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
