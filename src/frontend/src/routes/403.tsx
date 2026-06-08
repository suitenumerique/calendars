import { createFileRoute } from "@tanstack/react-router";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";
import { SimpleLayout } from "@/features/layouts/components/simple/SimpleLayout";
import { GenericDisclaimer } from "@/features/ui/components/generic-disclaimer/GenericDisclaimer";

const ForbiddenPage = () => {
  const { t } = useTranslation();
  return (
    <GenericDisclaimer message={t("403.title")} imageSrc="/403-background.png">
      <Button href="/" icon={<Icon name="home" />}>
        {t("403.button")}
      </Button>
    </GenericDisclaimer>
  );
};

const ForbiddenRoute = () => (
  <SimpleLayout>
    <ForbiddenPage />
  </SimpleLayout>
);

export const Route = createFileRoute("/403")({
  component: ForbiddenRoute,
});
