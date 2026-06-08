import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { useEffect } from "react";
import { useAuth } from "@/features/auth/Auth";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import { HeaderIcon, HeaderRight } from "@/features/layouts/components/header/Header";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { ResourceList } from "@/features/resources/components/ResourceList";
import { useResourcePrincipals } from "@/features/resources/api/useResourcePrincipals";
import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";

const ResourcesPage = () => {
  const { user } = useAuth();
  const { resources, isLoading, refresh } = useResourcePrincipals();
  const isEnabled = useFeatureFlag(FeatureFlag.ADMIN_RESOURCES);
  const navigate = useNavigate();

  useEffect(() => {
    if (!isEnabled) {
      void navigate({ to: "/", replace: true });
    }
  }, [isEnabled, navigate]);

  if (!user || !isEnabled) return null;

  return (
    <>
      <div className="resources-page">
        <ResourceList resources={resources} isLoading={isLoading} onRefresh={refresh} />
      </div>
      <Toaster />
    </>
  );
};

const ResourcesRoute = () => (
  <GlobalLayout>
    <MainLayout
      enableResize={false}
      hideLeftPanelOnDesktop={true}
      icon={<HeaderIcon />}
      rightHeaderContent={<HeaderRight />}
    >
      <ResourcesPage />
    </MainLayout>
  </GlobalLayout>
);

export const Route = createFileRoute("/resources")({
  component: ResourcesRoute,
});
