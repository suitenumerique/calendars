import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";

import { logout } from "@/features/auth/Auth";
import { GlobalLayout } from "@/features/layouts/components/global/GlobalLayout";
import {
  HeaderIcon,
  HeaderRight,
} from "@/features/layouts/components/header/Header";
import { GenericDisclaimer } from "@/features/ui/components/generic-disclaimer/GenericDisclaimer";

export default function NoAccessPage() {
  const { t } = useTranslation();
  return (
    <GenericDisclaimer
      message={t("no_access.title")}
      imageSrc="/assets/403-background.png"
    >
      <p>{t("no_access.description")}</p>
      <Button onClick={() => logout()}>{t("no_access.button")}</Button>
    </GenericDisclaimer>
  );
}

NoAccessPage.getLayout = function getLayout(page: React.ReactElement) {
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
