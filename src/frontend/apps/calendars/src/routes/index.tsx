import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Auth, useAuth } from "@/features/auth/Auth";
import { SESSION_STORAGE_REDIRECT_AFTER_LOGIN_URL } from "@/features/api/fetchApi";
import { CalendarContextProvider } from "@/features/calendar/contexts";
import { LeftPanel } from "@/features/calendar/components";
import { Scheduler } from "@/features/calendar/components/scheduler/Scheduler";
import { HomePage } from "@/features/home/HomePage";
import { HeaderIcon, HeaderRight } from "@/features/layouts/components/header/Header";
import { useLeftPanel } from "@/features/layouts/contexts/LeftPanelContext";
import { LeftPanelMobile } from "@/features/layouts/components/left-panel/LeftPanelMobile";
import { MailboxContextProvider } from "@/features/mailbox/MailboxContext";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";
import { Toaster } from "@/features/ui/components/toaster/Toaster";

function AuthenticatedView() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { isLeftPanelOpen, setIsLeftPanelOpen } = useLeftPanel();

  useEffect(() => {
    if (user?.can_access === false) {
      void navigate({ to: "/no-access" });
      return;
    }
    const attemptedUrl = sessionStorage.getItem(SESSION_STORAGE_REDIRECT_AFTER_LOGIN_URL);
    if (attemptedUrl) {
      sessionStorage.removeItem(SESSION_STORAGE_REDIRECT_AFTER_LOGIN_URL);
      try {
        const url = new URL(attemptedUrl, window.location.origin);
        if (url.origin === window.location.origin && url.pathname !== "/") {
          void navigate({ to: url.pathname + url.search + url.hash });
        }
      } catch {
        // ignore invalid URLs
      }
    }
  }, [user, navigate]);

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
  return (
    <div className="calendars__home calendars__home--feedback">
      <MainLayout
        enableResize
        hideLeftPanelOnDesktop={true}
        leftPanelContent={<LeftPanelMobile />}
        icon={<HeaderIcon />}
        rightHeaderContent={<HeaderRight />}
      >
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

const IndexPage = () => {
  const { t } = useTranslation();
  useEffect(() => {
    document.title = t("app_title");
  }, [t]);
  return (
    <Auth>
      <IndexContent />
    </Auth>
  );
};

export const Route = createFileRoute("/")({
  component: IndexPage,
});
