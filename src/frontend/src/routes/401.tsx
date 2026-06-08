import { createFileRoute } from "@tanstack/react-router";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";
import { login } from "@/features/auth/Auth";
import { SimpleLayout } from "@/features/layouts/components/simple/SimpleLayout";
import { GenericDisclaimer } from "@/features/ui/components/generic-disclaimer/GenericDisclaimer";

const UnauthorizedPage = () => {
  const { t } = useTranslation();
  return (
    <GenericDisclaimer message={t("401.title")} imageSrc="/401-background.png">
      <Button onClick={() => login()}>{t("401.button")}</Button>
    </GenericDisclaimer>
  );
};

const UnauthorizedRoute = () => (
  <SimpleLayout>
    <UnauthorizedPage />
  </SimpleLayout>
);

export const Route = createFileRoute("/401")({
  component: UnauthorizedRoute,
});
