import { useMemo, useState, useCallback } from "react";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { DropdownMenu, type DropdownMenuOption } from "@gouvfr-lasuite/ui-kit";
import { ChevronDown } from "@gouvfr-lasuite/ui-kit/icons";
import { useTranslation } from "react-i18next";
import { useCalendarLocale } from "../../../hooks/useCalendarLocale";
import { ChevronLeft, ChevronRight } from "@gouvfr-lasuite/ui-kit/icons";

import type { MobileToolbarProps } from "../types";

function formatMobileTitle(currentDate: Date, intlLocale: string): string {
  return new Intl.DateTimeFormat(intlLocale, {
    month: "long",
    year: "numeric",
  }).format(currentDate);
}

export const MobileToolbar = ({
  currentView,
  currentDate,
  onViewChange,
  onWeekPrev,
  onWeekNext,
  onTodayClick,
}: MobileToolbarProps) => {
  const { t } = useTranslation();
  const { intlLocale } = useCalendarLocale();
  const [isViewDropdownOpen, setIsViewDropdownOpen] = useState(false);

  const handleViewChange = useCallback(
    (value: string) => {
      onViewChange(value);
      setIsViewDropdownOpen(false);
    },
    [onViewChange],
  );

  const viewOptions: DropdownMenuOption[] = useMemo(
    () => [
      {
        value: "timeGridDay",
        label: t("calendar.views.mobile.oneDay"),
        callback: () => handleViewChange("timeGridDay"),
      },
      {
        value: "timeGridWorkWeek",
        label: t("calendar.views.mobile.workWeek"),
        callback: () => handleViewChange("timeGridWorkWeek"),
      },
      {
        value: "timeGridWeek",
        label: t("calendar.views.mobile.week"),
        callback: () => handleViewChange("timeGridWeek"),
      },
      {
        value: "listWeek",
        label: t("calendar.views.mobile.list"),
        callback: () => handleViewChange("listWeek"),
      },
    ],
    [t, handleViewChange],
  );

  const currentViewLabel = useMemo(() => {
    const option = viewOptions.find((opt) => opt.value === currentView);
    return option?.label || t("calendar.views.mobile.oneDay");
  }, [currentView, viewOptions, t]);

  const title = useMemo(
    () => formatMobileTitle(currentDate, intlLocale),
    [currentDate, intlLocale],
  );

  return (
    <div className="mobile-toolbar">
      <div className="mobile-toolbar__nav">
        <Button
          color="neutral"
          variant="bordered"
          size="small"
          onClick={onTodayClick}
          className="mobile-toolbar__today-btn"
        >
          {t("calendar.views.today")}
        </Button>

        <div className="mobile-toolbar__nav-arrows">
          <Button
            color="neutral"
            variant="tertiary"
            size="small"
            onClick={onWeekPrev}
            icon={<ChevronLeft />}
            aria-label={t("calendar.navigation.previous")}
          />
          <Button
            color="neutral"
            variant="tertiary"
            size="small"
            onClick={onWeekNext}
            icon={<ChevronRight />}
            aria-label={t("calendar.navigation.next")}
          />
        </div>

        <span className="mobile-toolbar__date-title">{title}</span>

        <div className="mobile-toolbar__view-wrapper">
          <DropdownMenu
            options={viewOptions}
            isOpen={isViewDropdownOpen}
            onOpenChange={setIsViewDropdownOpen}
            selectedValues={[currentView]}
          >
            <button
              className="mobile-toolbar__view-selector"
              onClick={() => setIsViewDropdownOpen(!isViewDropdownOpen)}
              type="button"
              aria-expanded={isViewDropdownOpen}
              aria-haspopup="listbox"
            >
              <span>{currentViewLabel}</span>
              <ChevronDown
                className={`mobile-toolbar__view-arrow ${
                  isViewDropdownOpen ? "mobile-toolbar__view-arrow--open" : ""
                }`}
              />
            </button>
          </DropdownMenu>
        </div>
      </div>
    </div>
  );
};
