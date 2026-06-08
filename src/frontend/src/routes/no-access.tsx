import { createFileRoute } from "@tanstack/react-router";
import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";
import { logout } from "@/features/auth/Auth";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import { HeaderIcon, HeaderRight } from "@/features/layouts/components/header/Header";
import { GenericDisclaimer } from "@/features/ui/components/generic-disclaimer/GenericDisclaimer";

const NoAccessPage = () => {
  const { t } = useTranslation();
  return (
    <GenericDisclaimer message={t("no_access.title")} imageSrc="/403-background.png">
      <p>{t("no_access.description")}</p>
      <Button onClick={() => logout()}>{t("no_access.button")}</Button>
    </GenericDisclaimer>
  );
};

const NoAccessRoute = () => (
  <GlobalLayout noRedirect>
    <MainLayout
      enableResize={false}
      hideLeftPanelOnDesktop={true}
      icon={<HeaderIcon />}
      rightHeaderContent={<HeaderRight />}
    >
      <NoAccessPage />
    </MainLayout>
  </GlobalLayout>
);

export const Route = createFileRoute("/no-access")({
  component: NoAccessRoute,
});
