import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { useEffect } from "react";
import { useAuth } from "@/features/auth/Auth";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import { HeaderIcon, HeaderRight } from "@/features/layouts/components/header/Header";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { ChannelList } from "@/features/integrations/components/ChannelList";
import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";

const IntegrationsPage = () => {
  const { user } = useAuth();
  const isEnabled = useFeatureFlag(FeatureFlag.ADMIN_CHANNELS);
  const navigate = useNavigate();

  useEffect(() => {
    if (!isEnabled) {
      void navigate({ to: "/", replace: true });
    }
  }, [isEnabled, navigate]);

  if (!user || !isEnabled) return null;

  return (
    <>
      <div className="integrations-page">
        <ChannelList />
      </div>
      <Toaster />
    </>
  );
};

const IntegrationsRoute = () => (
  <GlobalLayout>
    <MainLayout
      enableResize={false}
      hideLeftPanelOnDesktop={true}
      icon={<HeaderIcon />}
      rightHeaderContent={<HeaderRight />}
    >
      <IntegrationsPage />
    </MainLayout>
  </GlobalLayout>
);

export const Route = createFileRoute("/integrations")({
  component: IntegrationsRoute,
});
