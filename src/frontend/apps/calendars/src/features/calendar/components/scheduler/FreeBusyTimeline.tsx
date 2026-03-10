import { useEffect, useRef, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { createCalendar, destroyCalendar, ResourceTimeline } from "@event-calendar/core";
import type { FreeBusyResponse } from "../../services/dav/types/caldav-service";

interface FreeBusyTimelineProps {
  date: Date;
  attendees: FreeBusyResponse[];
  displayNames?: Record<string, string>;
  eventStart: Date;
  eventEnd: Date;
  isLoading: boolean;
  onDateChange: (date: Date) => void;
  onTimeSelect: (start: Date, end: Date) => void;
}

/** Map freebusy type to a background color. */
const BUSY_COLORS: Record<string, string> = {
  BUSY: "rgba(26, 115, 232, 0.4)",
  "BUSY-UNAVAILABLE": "rgba(95, 99, 104, 0.5)",
  "BUSY-TENTATIVE": "rgba(26, 115, 232, 0.2)",
};

export const FreeBusyTimeline = ({
  date,
  attendees,
  displayNames,
  eventStart,
  eventEnd,
  isLoading,
  onDateChange,
  onTimeSelect,
}: FreeBusyTimelineProps) => {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const calendarRef = useRef<ReturnType<typeof createCalendar> | null>(null);
  const handlersRef = useRef({ onTimeSelect, onDateChange });

  useEffect(() => {
    handlersRef.current = { onTimeSelect, onDateChange };
  });

  const eventDurationMs = eventEnd.getTime() - eventStart.getTime();
  const eventDurationRef = useRef(eventDurationMs);
  useEffect(() => {
    eventDurationRef.current = eventDurationMs;
  }, [eventDurationMs]);

  const dateStr = date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });

  // Map attendees → resources, using displayNames for friendly labels
  const resources = useMemo(
    () =>
      attendees.map((a) => ({
        id: a.attendee,
        title:
          displayNames?.[a.attendee] ??
          displayNames?.[a.attendee.toLowerCase()] ??
          a.attendee.split("@")[0],
      })),
    [attendees, displayNames],
  );

  // Map busy periods → background events + proposed event overlay
  const events = useMemo(() => {
    const allEvents: {
      id: string;
      resourceIds: string[];
      start: Date;
      end: Date;
      display?: string;
      backgroundColor?: string;
      title?: string;
    }[] = attendees.flatMap((a) =>
      a.periods.map((period, idx) => ({
        id: `busy-${a.attendee}-${idx}`,
        resourceIds: [a.attendee],
        start: period.start,
        end: period.end,
        display: "background",
        backgroundColor: BUSY_COLORS[period.type] ?? BUSY_COLORS.BUSY,
      })),
    );

    return allEvents;
  }, [attendees, date, resources]);

  // Count conflicts
  const eventOnThisDay =
    eventStart.toDateString() === date.toDateString() ||
    eventEnd.toDateString() === date.toDateString() ||
    (eventStart < date && eventEnd > date);
  const conflictCount = eventOnThisDay
    ? attendees.filter((a) =>
        a.periods.some((p) => p.start < eventEnd && p.end > eventStart),
      ).length
    : 0;

  // Create / destroy calendar instance
  useEffect(() => {
    if (!containerRef.current) return;

    const ec = createCalendar(containerRef.current, [ResourceTimeline], {
      view: "resourceTimelineDay",
      headerToolbar: false,
      slotMinTime: "07:00",
      slotMaxTime: "24:00",
      slotDuration: "01:00",
      height: "auto",
      date,
      resources,
      events,
      editable: false,
      selectable: false,
      dateClick: (info: { date: Date; resource?: { id: string } }) => {
        const clickedDate = info.date;
        const dur = eventDurationRef.current;
        const newEnd = new Date(clickedDate.getTime() + dur);
        handlersRef.current.onTimeSelect(clickedDate, newEnd);
      },
    });

    calendarRef.current = ec;

    // Make the time grid areas scrollable while keeping sidebar fixed
    const GRID_WIDTH = 1100;
    requestAnimationFrame(() => {
      if (!containerRef.current) return;
      // Structure: .ec-main > .ec-header, .ec-main > .ec-body
      const header = containerRef.current.querySelector(
        ".ec-header",
      ) as HTMLElement | null;
      const body = containerRef.current.querySelector(
        ".ec-body",
      ) as HTMLElement | null;
      if (!header || !body) return;

      // The grid inside header/body holds the time slots
      const headerGrid = header.querySelector(".ec-grid") as HTMLElement | null;
      const bodyGrid = body.querySelector(".ec-grid") as HTMLElement | null;
      if (!headerGrid || !bodyGrid) return;

      headerGrid.style.minWidth = `${GRID_WIDTH}px`;
      bodyGrid.style.minWidth = `${GRID_WIDTH}px`;

      // Make the body scrollable, hide header scrollbar
      body.style.overflowX = "auto";
      header.style.overflowX = "hidden";

      // Sync header scroll when body scrolls
      const onBodyScroll = () => {
        header.scrollLeft = body.scrollLeft;
      };
      body.addEventListener("scroll", onBodyScroll);

      // Scroll to ~8 AM (1 hour into the 7:00-24:00 range)
      const scrollPos = (1 / 17) * GRID_WIDTH;
      body.scrollLeft = scrollPos;
      header.scrollLeft = scrollPos;

      // Inject a single proposed-time overlay spanning all rows
      const startsOnDay = eventStart.toDateString() === date.toDateString();
      const endsOnDay = eventEnd.toDateString() === date.toDateString();
      const spansDay = eventStart < date && eventEnd > date;
      if ((startsOnDay || endsOnDay || spansDay) && resources.length > 0) {
        const SLOT_MIN = 7; // slotMinTime hours
        const SLOT_MAX = 24; // slotMaxTime hours
        const totalHours = SLOT_MAX - SLOT_MIN;
        const startH = startsOnDay
          ? eventStart.getHours() + eventStart.getMinutes() / 60
          : SLOT_MIN;
        const endH = endsOnDay
          ? eventEnd.getHours() + eventEnd.getMinutes() / 60
          : SLOT_MAX;
        const leftPct = ((Math.max(startH, SLOT_MIN) - SLOT_MIN) / totalHours) * 100;
        const rightPct = ((Math.min(endH, SLOT_MAX) - SLOT_MIN) / totalHours) * 100;

        if (rightPct > leftPct) {
          const overlay = document.createElement("div");
          overlay.className = "freebusy-proposed-overlay";
          overlay.style.position = "absolute";
          overlay.style.top = "0";
          overlay.style.bottom = "0";
          overlay.style.left = `${leftPct}%`;
          overlay.style.width = `${rightPct - leftPct}%`;
          overlay.style.pointerEvents = "none";
          overlay.style.zIndex = "5";

          bodyGrid.style.position = "relative";
          bodyGrid.appendChild(overlay);
        }
      }
    });

    return () => {
      if (calendarRef.current) {
        destroyCalendar(calendarRef.current);
        calendarRef.current = null;
      }
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
      }
    };
    // Recreate when data changes
  }, [date, resources, events, eventStart, eventEnd]);

  const handlePrev = useCallback(() => {
    const prev = new Date(date);
    prev.setDate(prev.getDate() - 1);
    onDateChange(prev);
  }, [date, onDateChange]);

  const handleNext = useCallback(() => {
    const next = new Date(date);
    next.setDate(next.getDate() + 1);
    onDateChange(next);
  }, [date, onDateChange]);

  return (
    <div className="freebusy-timeline">
      <div className="freebusy-timeline__header">
        <button
          type="button"
          className="freebusy-timeline__nav"
          onClick={handlePrev}
          aria-label={t("scheduling.previousDay")}
        >
          <span className="material-icons">chevron_left</span>
        </button>
        <span className="freebusy-timeline__date">{dateStr}</span>
        <button
          type="button"
          className="freebusy-timeline__nav"
          onClick={handleNext}
          aria-label={t("scheduling.nextDay")}
        >
          <span className="material-icons">chevron_right</span>
        </button>
        {isLoading && (
          <span className="freebusy-timeline__loading">
            <span className="material-icons freebusy-timeline__spinner">
              sync
            </span>
          </span>
        )}
        {!isLoading && eventOnThisDay && (
          <span
            className={`freebusy-timeline__status ${
              conflictCount > 0
                ? "freebusy-timeline__status--conflict"
                : "freebusy-timeline__status--ok"
            }`}
          >
            {conflictCount > 0
              ? t("scheduling.conflicts", { count: conflictCount })
              : t("scheduling.noConflicts")}
          </span>
        )}
      </div>

      {attendees.length === 0 && !isLoading ? (
        <div className="freebusy-timeline__empty">
          {t("scheduling.addAttendeesToSeeAvailability")}
        </div>
      ) : (
        <div ref={containerRef} className="freebusy-timeline__calendar" />
      )}
    </div>
  );
};
