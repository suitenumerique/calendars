import { useEffect } from "react";

import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import Head from "next/head";
import { useTranslation } from "next-i18next";

import { login, useAuth } from "@/features/auth/Auth";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import {
  HeaderIcon,
  HeaderRight,
} from "@/features/layouts/components/header/Header";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { ResourceList } from "@/features/resources/components/ResourceList";
import { useResourcePrincipals } from "@/features/resources/api/useResourcePrincipals";

export default function ResourcesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { resources, isLoading, refresh } = useResourcePrincipals();

  useEffect(() => {
    if (!user) {
      login(window.location.href);
    } else if (user.can_access === false) {
      window.location.href = "/no-access";
    }
  }, [user]);

  if (!user || user.can_access === false) {
    return <SpinnerPage />;
  }

  return (
    <>
      <Head>
        <title>
          {t("resources.title")} - {t("app_title")}
        </title>
        <meta name="description" content={t("resources.description")} />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.png" />
      </Head>

      <div className="resources-page">
        <ResourceList
          resources={resources}
          isLoading={isLoading}
          onRefresh={refresh}
        />
      </div>

      <Toaster />
    </>
  );
}

ResourcesPage.getLayout = function getLayout(page: React.ReactElement) {
  return (
    <GlobalLayout>
      <MainLayout
        enableResize={false}
        hideLeftPanelOnDesktop={true}
        icon={<HeaderIcon />}
        rightHeaderContent={<HeaderRight />}
      >
        {page}
      </MainLayout>
    </GlobalLayout>
  );
};
