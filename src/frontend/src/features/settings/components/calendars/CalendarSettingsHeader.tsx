import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/ui-components";
import { ArrowLeft } from "@gouvfr-lasuite/ui-components/icons";
import { useNavigate } from "@tanstack/react-router";

export const CalendarSettingsHeader = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="calendar-settings__header">
      <Button
        color="neutral"
        size="small"
        icon={<ArrowLeft />}
        onClick={() => void navigate({ to: "/" })}
        aria-label={t("app_title")}
      />
      <h2>{t("settings.calendars.title")}</h2>
    </div>
  );
};
