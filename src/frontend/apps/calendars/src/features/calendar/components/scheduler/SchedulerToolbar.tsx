/**
 * SchedulerToolbar - Custom toolbar for EventCalendar.
 * Replaces the native toolbar with React components using Cunningham design system.
 */

import { useMemo, useState, useRef, useEffect, useCallback } from "react";

import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useTranslation } from "react-i18next";

import type { SchedulerToolbarProps } from "./types";

type ViewOption = {
  value: string;
  label: string;
};

export const SchedulerToolbar = ({
  calendarRef,
  currentView,
  viewTitle,
  onViewChange,
}: SchedulerToolbarProps) => {
  const { t } = useTranslation();
  const [isViewDropdownOpen, setIsViewDropdownOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const isOpenRef = useRef(isViewDropdownOpen);

  // Keep ref in sync with state to avoid stale closures
  isOpenRef.current = isViewDropdownOpen;

  const viewOptions: ViewOption[] = useMemo(
    () => [
      { value: "timeGridDay", label: t("calendar.views.day") },
      { value: "timeGridWeek", label: t("calendar.views.week") },
      { value: "dayGridMonth", label: t("calendar.views.month") },
      { value: "listWeek", label: t("calendar.views.listWeek") },
    ],
    [t],
  );

  const currentViewLabel = useMemo(() => {
    const option = viewOptions.find((opt) => opt.value === currentView);
    return option?.label || t("calendar.views.week");
  }, [currentView, viewOptions, t]);

  // Handle click outside to close dropdown (uses ref to avoid stale closure)
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        isOpenRef.current &&
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsViewDropdownOpen(false);
        setFocusedIndex(-1);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Handle keyboard events for accessibility
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isOpenRef.current) return;

      switch (event.key) {
        case "Escape":
          setIsViewDropdownOpen(false);
          setFocusedIndex(-1);
          triggerRef.current?.focus();
          break;
        case "ArrowDown":
          event.preventDefault();
          setFocusedIndex((prev) =>
            prev < viewOptions.length - 1 ? prev + 1 : 0,
          );
          break;
        case "ArrowUp":
          event.preventDefault();
          setFocusedIndex((prev) =>
            prev > 0 ? prev - 1 : viewOptions.length - 1,
          );
          break;
        case "Tab":
          setIsViewDropdownOpen(false);
          setFocusedIndex(-1);
          break;
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [viewOptions.length]);

  const handleToday = useCallback(() => {
    calendarRef.current?.setOption("date", new Date());
  }, [calendarRef]);

  const handlePrev = useCallback(() => {
    calendarRef.current?.prev();
  }, [calendarRef]);

  const handleNext = useCallback(() => {
    calendarRef.current?.next();
  }, [calendarRef]);

  const handleViewChange = useCallback(
    (value: string) => {
      calendarRef.current?.setOption("view", value);
      onViewChange?.(value);
      setIsViewDropdownOpen(false);
    },
    [calendarRef, onViewChange],
  );

  const toggleViewDropdown = useCallback(() => {
    setIsViewDropdownOpen((prev) => {
      if (!prev) {
        // Opening: set focus to current view
        const currentIndex = viewOptions.findIndex(
          (opt) => opt.value === currentView,
        );
        setFocusedIndex(currentIndex >= 0 ? currentIndex : 0);
      } else {
        setFocusedIndex(-1);
      }
      return !prev;
    });
  }, [viewOptions, currentView]);

  const handleKeyDownOnTrigger = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === "ArrowDown" && !isViewDropdownOpen) {
        event.preventDefault();
        setIsViewDropdownOpen(true);
        const currentIndex = viewOptions.findIndex(
          (opt) => opt.value === currentView,
        );
        setFocusedIndex(currentIndex >= 0 ? currentIndex : 0);
      }
    },
    [isViewDropdownOpen, viewOptions, currentView],
  );

  const handleKeyDownOnOption = useCallback(
    (event: React.KeyboardEvent, value: string) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handleViewChange(value);
        triggerRef.current?.focus();
      }
    },
    [handleViewChange],
  );

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

      <div className="scheduler-toolbar__right" ref={dropdownRef}>
        <button
          ref={triggerRef}
          type="button"
          className="scheduler-toolbar__view-trigger"
          onClick={toggleViewDropdown}
          onKeyDown={handleKeyDownOnTrigger}
          aria-expanded={isViewDropdownOpen}
          aria-haspopup="listbox"
        >
          <span>{currentViewLabel}</span>
          <span
            className={`material-icons scheduler-toolbar__view-arrow ${isViewDropdownOpen ? "scheduler-toolbar__view-arrow--open" : ""}`}
          >
            expand_more
          </span>
        </button>

        {isViewDropdownOpen && (
          <div className="scheduler-toolbar__view-dropdown" role="listbox">
            {viewOptions.map((option, index) => (
              <button
                key={option.value}
                className={`scheduler-toolbar__view-option ${currentView === option.value ? "scheduler-toolbar__view-option--selected" : ""} ${focusedIndex === index ? "scheduler-toolbar__view-option--focused" : ""}`}
                onClick={() => handleViewChange(option.value)}
                onKeyDown={(e) => handleKeyDownOnOption(e, option.value)}
                role="option"
                aria-selected={currentView === option.value}
                tabIndex={focusedIndex === index ? 0 : -1}
                ref={(el) => {
                  if (focusedIndex === index && el) {
                    el.focus();
                  }
                }}
              >
                {option.label}
                {currentView === option.value && (
                  <span className="material-icons scheduler-toolbar__view-check">
                    check
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default SchedulerToolbar;
