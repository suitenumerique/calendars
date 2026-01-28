/**
 * SchedulerToolbar - Custom toolbar for EventCalendar.
 * Replaces the native toolbar with React components using Cunningham design system.
 */

import { useMemo, useState, useCallback } from "react";

import { Button } from "@gouvfr-lasuite/cunningham-react";
import { DropdownMenu, type DropdownMenuOption } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";

import type { SchedulerToolbarProps } from "./types";

export const SchedulerToolbar = ({
  calendarRef,
  currentView,
  viewTitle,
  onViewChange,
}: SchedulerToolbarProps) => {
  const { t } = useTranslation();
  const [isViewDropdownOpen, setIsViewDropdownOpen] = useState(false);

  const handleViewChange = useCallback(
    (value: string) => {
      calendarRef.current?.setOption("view", value);
      onViewChange?.(value);
      setIsViewDropdownOpen(false);
    },
    [calendarRef, onViewChange],
  );

  const viewOptions: DropdownMenuOption[] = useMemo(
    () => [
      {
        value: "timeGridDay",
        label: t("calendar.views.day"),
        callback: () => handleViewChange("timeGridDay"),
      },
      {
        value: "timeGridWeek",
        label: t("calendar.views.week"),
        callback: () => handleViewChange("timeGridWeek"),
      },
      {
        value: "dayGridMonth",
        label: t("calendar.views.month"),
        callback: () => handleViewChange("dayGridMonth"),
      },
      {
        value: "listWeek",
        label: t("calendar.views.listWeek"),
        callback: () => handleViewChange("listWeek"),
      },
    ],
    [t, handleViewChange],
  );

  const currentViewLabel = useMemo(() => {
    const option = viewOptions.find((opt) => opt.value === currentView);
    return option?.label || t("calendar.views.week");
  }, [currentView, viewOptions, t]);

  const handleToday = useCallback(() => {
    calendarRef.current?.setOption("date", new Date());
  }, [calendarRef]);

  const handlePrev = useCallback(() => {
    calendarRef.current?.prev();
  }, [calendarRef]);

  const handleNext = useCallback(() => {
    calendarRef.current?.next();
  }, [calendarRef]);

  return (
    <div className="scheduler-toolbar">
      <div className="scheduler-toolbar__left">
        <Button color="neutral" variant="bordered" onClick={handleToday}>
          {t("calendar.views.today")}
        </Button>

        <div className="scheduler-toolbar__nav">
          <Button
            color="neutral"
            variant="tertiary"
            onClick={handlePrev}
            icon={<span className="material-icons">chevron_left</span>}
            aria-label={t("calendar.navigation.previous")}
          />

          <Button
            color="neutral"
            variant="tertiary"
            onClick={handleNext}
            icon={<span className="material-icons">chevron_right</span>}
            aria-label={t("calendar.navigation.next")}
          />
        </div>
      </div>

      <div className="scheduler-toolbar__center">
        <h2 className="scheduler-toolbar__title">{viewTitle}</h2>
      </div>

      <div className="scheduler-toolbar__right">
        <DropdownMenu
          options={viewOptions}
          isOpen={isViewDropdownOpen}
          onOpenChange={setIsViewDropdownOpen}
          selectedValues={[currentView]}
        >
          <Button
            iconPosition="right"
            color="neutral"
            variant="tertiary"
            onClick={() => setIsViewDropdownOpen(!isViewDropdownOpen)}
            aria-expanded={isViewDropdownOpen}
            icon={
              <span
                className={`material-icons scheduler-toolbar__view-arrow ${isViewDropdownOpen ? "scheduler-toolbar__view-arrow--open" : ""}`}
              >
                expand_more
              </span>
            }
            aria-haspopup="listbox"
          >
            <span>{currentViewLabel}</span>
          </Button>
        </DropdownMenu>
      </div>
    </div>
  );
};

export default SchedulerToolbar;
