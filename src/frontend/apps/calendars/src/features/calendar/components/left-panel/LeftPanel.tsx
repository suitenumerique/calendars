/**
 * LeftPanel component - Calendar sidebar with mini calendar and calendar list.
 */

import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button, useModal } from "@gouvfr-lasuite/cunningham-react";
import { useNavigate } from "@tanstack/react-router";
import { IcsEvent } from "ts-ics";
import { useAuth } from "@/features/auth/Auth";
import { useIsMobile } from "@/hooks/useIsMobile";
import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";
import { CalendarList } from "../calendar-list";
import { MiniCalendar } from "./MiniCalendar";
import { EventModal } from "../scheduler/EventModal";
import { useCalendarContext } from "../../contexts";
import { useLeftPanel } from "@/features/layouts/contexts/LeftPanelContext";
import { Building, Clock, Plus, Puzzle } from "@gouvfr-lasuite/ui-kit/icons";
const BROWSER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

/**
 * Get rounded start and end times for a new event.
 * Rounds down to the current hour, end is 1 hour later.
 * Example: 14:30 -> start: 14:00, end: 15:00
 */
const getDefaultEventTimes = () => {
  const now = new Date();
  const start = new Date(now);
  start.setMinutes(0, 0, 0);

  const end = new Date(start);
  end.setHours(end.getHours() + 1);

  return { start, end };
};

export const LeftPanel = () => {
  const { t } = useTranslation();
  const modal = useModal();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { user } = useAuth();
  const { setIsLeftPanelOpen } = useLeftPanel();

  const isResourcesEnabled = useFeatureFlag(FeatureFlag.ADMIN_RESOURCES);
  const isChannelsEnabled = useFeatureFlag(FeatureFlag.ADMIN_CHANNELS);
  const isAvailabilitiesEnabled = useFeatureFlag(FeatureFlag.ADMIN_AVAILABILITIES);

  const { selectedDate, setSelectedDate, orderedCalendars, caldavService, adapter, calendarRef } =
    useCalendarContext();

  // Get default calendar URL — first in the displayed order (sidebar top).
  const defaultCalendarUrl = orderedCalendars[0]?.url || "";

  // Create default event with rounded times
  const defaultEvent = useMemo(() => {
    const { start, end } = getDefaultEventTimes();

    // Create "fake UTC" dates for the adapter
    const fakeUtcStart = new Date(
      Date.UTC(
        start.getFullYear(),
        start.getMonth(),
        start.getDate(),
        start.getHours(),
        start.getMinutes(),
        0,
      ),
    );
    const fakeUtcEnd = new Date(
      Date.UTC(
        end.getFullYear(),
        end.getMonth(),
        end.getDate(),
        end.getHours(),
        end.getMinutes(),
        0,
      ),
    );

    return {
      start: {
        date: fakeUtcStart,
        type: "DATE-TIME" as const,
        local: {
          date: fakeUtcStart,
          timezone: BROWSER_TIMEZONE,
          tzoffset: adapter.getTimezoneOffset(start, BROWSER_TIMEZONE),
        },
      },
      end: {
        date: fakeUtcEnd,
        type: "DATE-TIME" as const,
        local: {
          date: fakeUtcEnd,
          timezone: BROWSER_TIMEZONE,
          tzoffset: adapter.getTimezoneOffset(end, BROWSER_TIMEZONE),
        },
      },
    };
  }, [adapter]);

  // Handle save event
  const handleSave = useCallback(
    async (event: IcsEvent, calendarUrl: string) => {
      const result = await caldavService.createEvent({
        calendarUrl,
        event,
      });

      if (!result.success) {
        throw new Error(result.error || "Failed to create event");
      }

      // Refresh the calendar view
      if (calendarRef.current) {
        calendarRef.current.refetchEvents();
      }
    },
    [caldavService, calendarRef],
  );

  const handleClose = useCallback(() => {
    modal.close();
  }, [modal]);

  // On mobile, the desktop top-bar (Settings dropdown, user menu) is
  // hidden, so the only way to reach Working Hours / Resources /
  // Integrations is via the drawer. Mirror those links here so mobile
  // users aren't trapped on the calendar grid.
  const mobileNavItems = [
    ...(isAvailabilitiesEnabled
      ? [
          {
            label: t("settings.workingHours.title"),
            icon: <Clock />,
            to: "/availabilities" as const,
          },
        ]
      : []),
    ...(user?.can_admin && isResourcesEnabled
      ? [
          {
            label: t("resources.title"),
            icon: <Building />,
            to: "/resources" as const,
          },
        ]
      : []),
    ...(user?.can_admin && isChannelsEnabled
      ? [
          {
            label: t("integrations.title"),
            icon: <Puzzle />,
            to: "/integrations" as const,
          },
        ]
      : []),
  ];

  return (
    <>
      <div className="calendar-left-panel">
        <div className="calendar-left-panel__create">
          <Button onClick={modal.open} icon={<Plus />}>
            {t("calendar.leftPanel.newEvent")}
          </Button>
        </div>

        <MiniCalendar selectedDate={selectedDate} onDateSelect={setSelectedDate} />

        <div className="calendar-left-panel__divider" />

        <CalendarList />

        {isMobile && mobileNavItems.length > 0 && (
          <>
            <div className="calendar-left-panel__divider" />
            <nav className="calendar-left-panel__mobile-nav">
              {mobileNavItems.map((item) => (
                <button
                  key={item.to}
                  type="button"
                  className="calendar-left-panel__mobile-nav-item"
                  onClick={() => {
                    setIsLeftPanelOpen(false);
                    void navigate({ to: item.to });
                  }}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
            </nav>
          </>
        )}
      </div>

      {modal.isOpen && (
        <EventModal
          isOpen={modal.isOpen}
          mode="create"
          event={defaultEvent}
          calendarUrl={defaultCalendarUrl}
          calendars={orderedCalendars}
          adapter={adapter}
          onSave={handleSave}
          onClose={handleClose}
        />
      )}
    </>
  );
};
