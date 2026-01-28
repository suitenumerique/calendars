/**
 * Calendar page - Main calendar view with sidebar.
 */

import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import Head from "next/head";
import { useTranslation } from "next-i18next";

import { login, useAuth } from "@/features/auth/Auth";
import { LeftPanel } from "@/features/calendar/components";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import { HeaderRight } from "@/features/layouts/components/header/Header";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { Scheduler } from "@/features/calendar/components/scheduler/Scheduler";
import { CalendarContextProvider } from "@/features/calendar/contexts";

export default function CalendarPage() {
  const { t } = useTranslation();
  const { user } = useAuth();

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
        <div className="calendar-page__main">
          <Scheduler />
        </div>
      </div>

      <Toaster />
    </>
  );
}

CalendarPage.getLayout = function getLayout(page: React.ReactElement) {
  return (
    <CalendarContextProvider>
      <div className="calendars__calendar">
        <GlobalLayout>
          <MainLayout
            enableResize={false}
            leftPanelContent={<LeftPanel />}
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
    </CalendarContextProvider>
  );
};
