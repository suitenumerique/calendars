import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { useEffect } from "react";
import { useAuth } from "@/features/auth/Auth";
import { CalendarContextProvider } from "@/features/calendar/contexts";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import { HeaderIcon, HeaderRight } from "@/features/layouts/components/header/Header";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { WorkingHoursSettings } from "@/features/settings/components/WorkingHoursSettings";
import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";

const AvailabilitiesPage = () => {
  const { user } = useAuth();
  const isEnabled = useFeatureFlag(FeatureFlag.ADMIN_AVAILABILITIES);
  const navigate = useNavigate();

  useEffect(() => {
    if (!isEnabled) {
      void navigate({ to: "/", replace: true });
    }
  }, [isEnabled, navigate]);

  if (!user || !isEnabled) return null;

  return (
    <>
      <div className="settings-page">
        <WorkingHoursSettings />
      </div>
      <Toaster />
    </>
  );
};

const AvailabilitiesRoute = () => (
  <GlobalLayout>
    <CalendarContextProvider>
      <MainLayout
        enableResize={false}
        hideLeftPanelOnDesktop={true}
        icon={<HeaderIcon />}
        rightHeaderContent={<HeaderRight />}
      >
        <AvailabilitiesPage />
      </MainLayout>
    </CalendarContextProvider>
  </GlobalLayout>
);

export const Route = createFileRoute("/availabilities")({
  component: AvailabilitiesRoute,
});
