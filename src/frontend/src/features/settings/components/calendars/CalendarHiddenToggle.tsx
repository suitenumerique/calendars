import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Icon, IconType, Tooltip } from "@gouvfr-lasuite/ui-components";

interface CalendarHiddenToggleProps {
  hidden: boolean;
  /** Asks for the opposite state. It resolves when the change ends. */
  onToggle: () => Promise<unknown>;
}

/** An eye button that hides a calendar for the user, or shows it again (see `CalDavCalendar.hidden`). */
export const CalendarHiddenToggle = ({ hidden, onToggle }: CalendarHiddenToggleProps) => {
  const { t } = useTranslation();
  const [isPending, setIsPending] = useState(false);

  const handleClick = () => {
    setIsPending(true);
    void onToggle().finally(() => setIsPending(false));
  };

  const label = t(hidden ? "calendar.list.show" : "calendar.list.hide");
  const tooltip = t(hidden ? "settings.calendars.showTooltip" : "settings.calendars.hideTooltip");

  return (
    <Tooltip content={tooltip}>
      <Button
        color="neutral"
        variant="tertiary"
        size="small"
        aria-label={label}
        disabled={isPending}
        onClick={handleClick}
        icon={
          <Icon
            name={hidden ? "visibility_off" : "visibility"}
            type={IconType.OUTLINED}
            aria-hidden
          />
        }
      />
    </Tooltip>
  );
};
