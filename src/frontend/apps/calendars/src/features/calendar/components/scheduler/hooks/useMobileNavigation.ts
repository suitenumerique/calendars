import { useCallback, useMemo } from "react";
import { addDays, getWeekStart } from "@/utils/date";

import type { CalendarApi } from "../types";

interface UseMobileNavigationProps {
  currentDate: Date;
  firstDayOfWeek: number;
  calendarRef: React.RefObject<CalendarApi | null>;
}

export function useMobileNavigation({
  currentDate,
  firstDayOfWeek,
  calendarRef,
}: UseMobileNavigationProps) {
  const weekStart = useMemo(
    () => getWeekStart(currentDate, firstDayOfWeek),
    [currentDate, firstDayOfWeek],
  );

  const weekDays = useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  }, [weekStart]);

  const navigatePreservingScroll = useCallback(
    (date: Date) => {
      const ecBody = calendarRef.current
        ? (document.querySelector(".ec-main") as HTMLElement | null)
        : null;
      const scrollTop = ecBody?.scrollTop ?? 0;

      calendarRef.current?.setOption("date", date);

      requestAnimationFrame(() => {
        if (ecBody) ecBody.scrollTop = scrollTop;
      });
    },
    [calendarRef],
  );

  const handleWeekPrev = useCallback(() => {
    navigatePreservingScroll(addDays(currentDate, -7));
  }, [currentDate, navigatePreservingScroll]);

  const handleWeekNext = useCallback(() => {
    navigatePreservingScroll(addDays(currentDate, 7));
  }, [currentDate, navigatePreservingScroll]);

  const handleDayClick = useCallback(
    (date: Date) => {
      navigatePreservingScroll(date);
    },
    [navigatePreservingScroll],
  );

  const handleTodayClick = useCallback(() => {
    calendarRef.current?.setOption("date", new Date());
  }, [calendarRef]);

  return {
    weekStart,
    weekDays,
    handleWeekPrev,
    handleWeekNext,
    handleDayClick,
    handleTodayClick,
  };
}
