import { useTranslation } from "react-i18next";
import { Plus } from "@gouvfr-lasuite/ui-kit/icons";

import type { FloatingActionButtonProps } from "../types";

export const FloatingActionButton = ({ onClick }: FloatingActionButtonProps) => {
  const { t } = useTranslation();
  return (
    <button
      className="fab-create-event"
      onClick={onClick}
      type="button"
      aria-label={t("calendar.leftPanel.newEvent")}
    >
      <Plus className="fab-create-event__icon" aria-hidden="true" />
    </button>
  );
};
