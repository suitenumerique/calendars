import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { isSameDay, isToday } from "@/utils/date";
import { ChevronRight } from "@gouvfr-lasuite/ui-kit/icons";
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";

import type { MobileListViewProps, MobileListEvent } from "../types";

function groupEventsByDay(
  events: MobileListEvent[],
  weekDays: Date[],
): Map<string, MobileListEvent[]> {
  const grouped = new Map<string, MobileListEvent[]>();
  for (const day of weekDays) {
    grouped.set(day.toISOString(), []);
  }

  for (const event of events) {
    for (const day of weekDays) {
      if (isSameDay(event.start, day)) {
        grouped.get(day.toISOString())?.push(event);
      }
    }
  }

  for (const [, dayEvents] of grouped) {
    dayEvents.sort((a, b) => a.start.getTime() - b.start.getTime());
  }

  return grouped;
}

export const MobileListView = ({
  weekDays,
  events,
  intlLocale,
  onEventClick,
}: MobileListViewProps) => {
  const { t } = useTranslation();

  const eventsByDay = useMemo(() => groupEventsByDay(events, weekDays), [events, weekDays]);

  const dayHeaderFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(intlLocale, {
        weekday: "long",
        day: "numeric",
        month: "long",
      }),
    [intlLocale],
  );

  const timeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(intlLocale, {
        hour: "numeric",
        minute: "2-digit",
      }),
    [intlLocale],
  );

  return (
    <div className="mobile-list">
      {weekDays.map((day) => {
        const dayKey = day.toISOString();
        const dayEvents = eventsByDay.get(dayKey) ?? [];
        const dayIsToday = isToday(day);

        return (
          <div key={dayKey} className="mobile-list__day">
            <div className="mobile-list__day-header">
              <span
                className={`mobile-list__day-dot ${
                  dayIsToday ? "mobile-list__day-dot--today" : ""
                }`}
              />
              <span className="mobile-list__day-title">{dayHeaderFormatter.format(day)}</span>
              {dayIsToday && (
                <span className="mobile-list__today-tag">{t("calendar.views.today")}</span>
              )}
            </div>

            {dayEvents.length === 0 ? (
              <div className="mobile-list__empty">
                <Icon name="event_busy" type={IconType.OUTLINED} aria-hidden />
                <span className="mobile-list__empty-text">
                  {t("calendar.views.mobile.noEvents")}
                </span>
              </div>
            ) : (
              <div className="mobile-list__events">
                {dayEvents.map((event) => (
                  <button
                    key={String(event.id)}
                    className="mobile-list__event-card"
                    onClick={() => onEventClick(String(event.id), event.extendedProps)}
                    type="button"
                  >
                    <span
                      className="mobile-list__color-strip"
                      style={{ backgroundColor: event.backgroundColor }}
                    />
                    <div className="mobile-list__event-info">
                      <span className="mobile-list__event-title">
                        {event.title || t("calendar.event.titlePlaceholder")}
                      </span>
                      <span className="mobile-list__event-time">
                        {event.allDay
                          ? t("calendar.event.allDay")
                          : `${timeFormatter.format(event.start)} - ${timeFormatter.format(event.end)}`}
                      </span>
                    </div>
                    <ChevronRight />
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
