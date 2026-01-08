/**
 * Calendar page - Main calendar view with sidebar.
 */

import { useCallback, useState } from "react";

import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import Head from "next/head";
import { useTranslation } from "next-i18next";

import { login, useAuth } from "@/features/auth/Auth";
import { CalendarView, LeftPanel } from "@/features/calendar/components";
import { useCreateCalendarModal } from "@/features/calendar/components/CreateCalendarModal";
import { useCreateEventModal } from "@/features/calendar/hooks/useCreateEventModal";
import { useCalendars } from "@/features/calendar/hooks/useCalendars";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import { HeaderRight } from "@/features/layouts/components/header/Header";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";
import { Toaster } from "@/features/ui/components/toaster/Toaster";

export default function CalendarPage() {
  const { t } = useTranslation();
  const { user } = useAuth();

  // Calendar state
  const [selectedDate, setSelectedDate] = useState(new Date());

  // Fetch calendars for the sidebar
  const { data: calendars = [], isLoading: isLoadingCalendars } = useCalendars();

  // Create calendar modal
  const createCalendarModal = useCreateCalendarModal();

  // Create event modal
  const createEventModal = useCreateEventModal({ 
    calendars: calendars || [], 
    selectedDate 
  });

  // Handlers
  const handleDateSelect = useCallback((date: Date) => {
    setSelectedDate(date);
  }, []);

  const handleCreateEvent = useCallback(() => {
    createEventModal.open();
  }, [createEventModal]);

  const handleCreateCalendar = useCallback(() => {
    createCalendarModal.open();
  }, [createCalendarModal]);

  // Redirect to login if not authenticated
  if (!user) {
    if (typeof window !== "undefined") {
      login(window.location.href);
    }
    return <SpinnerPage />;
  }

  return (
    <>
      <Head>
        <title>Calendrier - {t("app_title")}</title>
        <meta name="description" content={t("app_description")} />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.png" />
      </Head>

      <div className="calendar-page">
        <div className="calendar-page__sidebar">
          <LeftPanel
            calendars={calendars}
            selectedDate={selectedDate}
            onDateSelect={handleDateSelect}
            onCreateEvent={handleCreateEvent}
            onCreateCalendar={handleCreateCalendar}
          />
        </div>
        <div className="calendar-page__main">
          <CalendarView
            selectedDate={selectedDate}
            onSelectDate={handleDateSelect}
          />
        </div>
      </div>

      {createCalendarModal.Modal}
      {createEventModal.Modal}
      <Toaster />
    </>
  );
}

CalendarPage.getLayout = function getLayout(page: React.ReactElement) {
  return (
    <div className="calendars__calendar">
      <GlobalLayout>
        <MainLayout
          enableResize
          hideLeftPanelOnDesktop={true}
          leftPanelContent={null}
          icon={
            <div className="calendars__header__left">
              <div className="calendars__header__logo" />
            </div>
          }
          rightHeaderContent={<HeaderRight />}
        >
          {page}
        </MainLayout>
      </GlobalLayout>
    </div>
  );
};
