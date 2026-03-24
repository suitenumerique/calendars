import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import Head from "next/head";
import { useTranslation } from "next-i18next";

import { useAuth } from "@/features/auth/Auth";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import {
  HeaderIcon,
  HeaderRight,
} from "@/features/layouts/components/header/Header";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { WorkingHoursSettings } from "@/features/settings/components/WorkingHoursSettings";
import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";
import { useRouter } from "next/router";
import { useEffect } from "react";

export default function SettingsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isEnabled = useFeatureFlag(FeatureFlag.ADMIN_AVAILABILITIES);
  const router = useRouter();

  useEffect(() => {
    if (!isEnabled) {
      void router.replace("/");
    }
  }, [isEnabled, router]);

  if (!user || !isEnabled) return null;

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
