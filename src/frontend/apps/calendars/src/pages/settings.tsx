import { useEffect } from "react";

import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import Head from "next/head";
import { useTranslation } from "next-i18next";
import { useRouter } from "next/router";

import { login, useAuth } from "@/features/auth/Auth";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import {
  HeaderIcon,
  HeaderRight,
} from "@/features/layouts/components/header/Header";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { WorkingHoursSettings } from "@/features/settings/components/WorkingHoursSettings";

export default function SettingsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!user) {
      login(window.location.href);
    } else if (user.can_access === false) {
      void router.push("/no-access");
    }
  }, [user, router]);

  if (!user || user.can_access === false) {
    return <SpinnerPage />;
  }

  return (
    <>
      <Head>
        <title>
          {t("settings.workingHours.title")} -{" "}
          {t("app_title")}
        </title>
        <meta
          name="description"
          content={t(
            "settings.workingHours.description",
          )}
        />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1"
        />
        <link rel="icon" href="/favicon.png" />
      </Head>

      <div className="settings-page">
        <WorkingHoursSettings />
      </div>

      <Toaster />
    </>
  );
}

SettingsPage.getLayout = function getLayout(
  page: React.ReactElement,
) {
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
