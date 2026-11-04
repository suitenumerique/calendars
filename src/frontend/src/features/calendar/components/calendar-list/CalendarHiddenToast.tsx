import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/ui-components";
import { useNavigate } from "@tanstack/react-router";
import type { ToastContentProps } from "react-toastify";

import { ToasterItem } from "@/features/ui/components/toaster/Toaster";

interface CalendarHiddenToastProps extends Partial<ToastContentProps> {
  onUndo: () => void;
}

/** Tells the user that a calendar is hidden. It offers to undo the hide or to open the settings. */
export const CalendarHiddenToast = ({ onUndo, closeToast }: CalendarHiddenToastProps) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const handleSettings = () => {
    closeToast?.();
    void navigate({ to: "/settings/calendars" });
  };

  const handleUndo = () => {
    closeToast?.();
    onUndo();
  };

  return (
    <ToasterItem type="info" closeButton closeToast={closeToast}>
      <span>{t("calendar.list.hiddenToast")}</span>
      <Button color="brand" variant="tertiary" size="small" onClick={handleUndo}>
        {t("calendar.list.undo")}
      </Button>
      <Button color="brand" variant="tertiary" size="small" onClick={handleSettings}>
        {t("settings.label")}
      </Button>
    </ToasterItem>
  );
};
