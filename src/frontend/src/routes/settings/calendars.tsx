import { createFileRoute } from "@tanstack/react-router";
import { MainLayout } from "@gouvfr-lasuite/ui-components";
import { useAuth } from "@/features/auth/Auth";
import { CalendarContextProvider } from "@/features/calendar/contexts";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import { HeaderIcon, HeaderRight } from "@/features/layouts/components/header/Header";
import { MailboxContextProvider } from "@/features/mailbox/MailboxContext";
import { CalendarSettings } from "@/features/settings/components/calendars/CalendarSettings";
import { Toaster } from "@/features/ui/components/toaster/Toaster";

const CalendarSettingsPage = () => {
  const { user } = useAuth();

  if (!user) return null;

  return (
    <>
      <div className="settings-page">
        <CalendarSettings />
      </div>
      <Toaster />
    </>
  );
};

const CalendarSettingsRoute = () => (
  <GlobalLayout>
    <MailboxContextProvider>
      <CalendarContextProvider>
        <MainLayout
          enableResize={false}
          hideLeftPanelOnDesktop={true}
          icon={<HeaderIcon />}
          rightHeaderContent={<HeaderRight />}
        >
          <CalendarSettingsPage />
        </MainLayout>
      </CalendarContextProvider>
    </MailboxContextProvider>
  </GlobalLayout>
);

export const Route = createFileRoute("/settings/calendars")({
  component: CalendarSettingsRoute,
});
