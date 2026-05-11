import Head from "next/head";
import { useTranslation } from "next-i18next";
import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { Auth, useAuth } from "@/features/auth/Auth";
import { useEffect } from "react";
import { useRouter } from "next/router";
import {
  HeaderIcon,
  HeaderRight,
} from "@/features/layouts/components/header/Header";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { LeftPanelMobile } from "@/features/layouts/components/left-panel/LeftPanelMobile";
import { LeftPanel } from "@/features/calendar/components";
import { useLeftPanel } from "@/features/layouts/contexts/LeftPanelContext";
import { CalendarContextProvider } from "@/features/calendar/contexts";
import { MailboxContextProvider } from "@/features/mailbox/MailboxContext";
import { Scheduler } from "@/features/calendar/components/scheduler/Scheduler";
import { HomePage } from "@/features/home/HomePage";
import { SESSION_STORAGE_REDIRECT_AFTER_LOGIN_URL } from "@/features/api/fetchApi";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";

function AuthenticatedView() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const router = useRouter();
  const { isLeftPanelOpen, setIsLeftPanelOpen } = useLeftPanel();

  useEffect(() => {
    if (user?.can_access === false) {
      void router.push("/no-access");
      return;
    }
    const attemptedUrl = sessionStorage.getItem(
      SESSION_STORAGE_REDIRECT_AFTER_LOGIN_URL,
    );
    if (attemptedUrl) {
      sessionStorage.removeItem(SESSION_STORAGE_REDIRECT_AFTER_LOGIN_URL);
      try {
        const url = new URL(attemptedUrl, window.location.origin);
        if (url.origin === window.location.origin && url.pathname !== "/") {
          void router.push(url.pathname + url.search + url.hash);
        }
      } catch {
        // ignore invalid URLs
      }
    }
  }, [user, router]);

  return (
    <MailboxContextProvider>
    <CalendarContextProvider>
      <div className="calendars__calendar">
        <MainLayout
          enableResize={false}
          leftPanelContent={<LeftPanel />}
          icon={<HeaderIcon />}
          rightHeaderContent={<HeaderRight />}
          isLeftPanelOpen={isLeftPanelOpen}
          setIsLeftPanelOpen={setIsLeftPanelOpen}
        >
          <Head>
            <title>{t("app_title")}</title>
            <meta name="description" content={t("app_description")} />
            <meta
              name="viewport"
              content="width=device-width, initial-scale=1"
            />
          </Head>
          <div className="calendar-page">
            <div className="calendar-page__main">
              <Scheduler />
            </div>
          </div>
          <Toaster />
        </MainLayout>
      </div>
    </CalendarContextProvider>
    </MailboxContextProvider>
  );
}

function AnonymousView() {
  const { t } = useTranslation();

  return (
    <div className="calendars__home calendars__home--feedback">
      <MainLayout
        enableResize
        hideLeftPanelOnDesktop={true}
        leftPanelContent={<LeftPanelMobile />}
        icon={<HeaderIcon />}
        rightHeaderContent={<HeaderRight />}
      >
        <Head>
          <title>{t("app_title")}</title>
          <meta name="description" content={t("app_description")} />
          <meta
            name="viewport"
            content="width=device-width, initial-scale=1"
          />
        </Head>
        <HomePage />
        <Toaster />
      </MainLayout>
    </div>
  );
}

function IndexContent() {
  const { user } = useAuth();

  if (user === undefined) {
    return <SpinnerPage />;
  }

  return user ? <AuthenticatedView /> : <AnonymousView />;
}

export default function IndexPage() {
  return (
    <Auth>
      <IndexContent />
    </Auth>
  );
}
