import {
  createContext,
  useContext,
  useRef,
  useMemo,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { CalDavService } from "../services/dav/CalDavService";
import { EventCalendarAdapter } from "../services/dav/EventCalendarAdapter";
import { caldavServerUrl } from "../utils/DavClient";
import { sortCalendars } from "../utils/calendar-order";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import { useAuth } from "@/features/auth/Auth";
import { deleteMailboxCalendar as deleteMailboxCalendarApi } from "@/features/mailbox/api";
import { setCalendarHiddenAndRefresh } from "./set-calendar-hidden";

import type {
  CalDavCalendar,
  CalDavCalendarCreate,
  CalDavCalendarUpdate,
  SharePrivilege,
} from "../services/dav/types/caldav-service";
import type { CalendarApi } from "../components/scheduler/types";

// The URLs of the calendars that the user unchecked in this browser. The
// key keeps its old name, so the choices of existing users stay.
const UNCHECKED_CALENDARS_KEY = "calendar-hidden-urls";

const loadUncheckedCalendarUrls = (): Set<string> => {
  try {
    const stored = localStorage.getItem(UNCHECKED_CALENDARS_KEY);
    if (stored) {
      return new Set(JSON.parse(stored) as string[]);
    }
  } catch {
    // Ignore parse errors
  }
  return new Set();
};

const saveUncheckedCalendarUrls = (uncheckedUrls: Set<string>) => {
  try {
    localStorage.setItem(UNCHECKED_CALENDARS_KEY, JSON.stringify([...uncheckedUrls]));
  } catch {
    // Ignore storage errors
  }
};

export interface CalendarContextType {
  calendarRef: React.RefObject<CalendarApi | null>;
  caldavService: CalDavService;
  adapter: EventCalendarAdapter;
  /** The calendars that the user did not hide (see `CalDavCalendar.hidden`). */
  davCalendars: CalDavCalendar[];
  /**
   * The calendars that the user did not hide, in the order of the
   * sidebar. Use this, not `davCalendars`, for a list that the user sees,
   * such as the event modal.
   */
  orderedCalendars: CalDavCalendar[];
  /** The calendars that the user hid (see `CalDavCalendar.hidden`). */
  hiddenCalendars: CalDavCalendar[];
  visibleCalendarUrls: Set<string>;
  isLoading: boolean;
  isConnected: boolean;
  currentDate: Date;
  setCurrentDate: (date: Date) => void;
  selectedDate: Date;
  setSelectedDate: (date: Date) => void;
  refreshCalendars: () => Promise<void>;
  toggleCalendarVisibility: (calendarUrl: string) => void;
  createCalendar: (params: CalDavCalendarCreate) => Promise<{ success: boolean; error?: string }>;
  updateCalendar: (
    calendarUrl: string,
    params: CalDavCalendarUpdate,
  ) => Promise<{ success: boolean; error?: string }>;
  deleteCalendar: (calendarUrl: string) => Promise<{ success: boolean; error?: string }>;
  /** Deletes a mailbox calendar for every user of the mailbox. */
  deleteMailboxCalendar: (
    calendarUrl: string,
    mailboxEmail: string,
  ) => Promise<{ success: boolean; error?: string }>;
  /**
   * Grants or updates access for the given emails in one CalDAV request.
   * A failed request can apply some of the changes.
   */
  shareCalendar: (
    calendarUrl: string,
    emails: string[],
    privilege?: SharePrivilege,
  ) => Promise<{ success: boolean; error?: string; status?: number }>;
  moveCalendar: (
    calendarUrl: string,
    direction: "up" | "down",
  ) => Promise<{ success: boolean; error?: string }>;
  /**
   * Hides the calendar for the user, or shows it again (see
   * `CalDavCalendar.hidden`). Success means that the server accepted the
   * change. A failed refresh after it shows its own error and keeps the
   * last calendars, so the list can still show the old state.
   */
  setCalendarHidden: (
    calendarUrl: string,
    hidden: boolean,
  ) => Promise<{ success: boolean; error?: string }>;
  goToDate: (date: Date) => void;
}

const CalendarContext = createContext<CalendarContextType | undefined>(undefined);

export const useCalendarContext = () => {
  const context = useContext(CalendarContext);
  if (!context) {
    throw new Error("useCalendarContext must be used within a CalendarContextProvider");
  }
  return context;
};

interface CalendarContextProviderProps {
  children: ReactNode;
}

export const CalendarContextProvider = ({ children }: CalendarContextProviderProps) => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const userEmail = user?.email;
  const calendarRef = useRef<CalendarApi | null>(null);
  const caldavService = useMemo(() => new CalDavService(), []);
  const adapter = useMemo(() => new EventCalendarAdapter(), []);
  const [allCalendars, setAllCalendars] = useState<CalDavCalendar[]>([]);
  const allCalendarsRef = useRef<CalDavCalendar[]>([]);
  allCalendarsRef.current = allCalendars;
  const [visibleCalendarUrls, setVisibleCalendarUrls] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [currentDate, setCurrentDate] = useState<Date>(new Date());
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());

  const { davCalendars, hiddenCalendars } = useMemo(
    () => ({
      davCalendars: allCalendars.filter((cal) => !cal.hidden),
      hiddenCalendars: allCalendars.filter((cal) => cal.hidden),
    }),
    [allCalendars],
  );

  const orderedCalendars = useMemo(() => sortCalendars(davCalendars), [davCalendars]);

  // A failed refresh keeps the calendars of the last fetch. An empty list
  // would show the onboarding, as if the user had no calendar.
  const refreshCalendars = useCallback(async () => {
    try {
      setIsLoading(true);
      const result = await caldavService.fetchCalendars();
      if (result.success && result.data) {
        setAllCalendars(result.data);
        // Visible = all calendars minus the URLs that the user unchecked in
        // this browser. New calendars are visible. This is not
        // `CalDavCalendar.hidden`: a hidden calendar is not in davCalendars.
        const unchecked = loadUncheckedCalendarUrls();
        setVisibleCalendarUrls(
          new Set(result.data.map((cal) => cal.url).filter((url) => !unchecked.has(url))),
        );
      } else {
        console.error("Error fetching calendars:", result.error);
        addToast(
          <ToasterItem type="error" closeButton>
            {t("calendar.error.fetchCalendars")}
          </ToasterItem>,
        );
      }
    } catch (error) {
      console.error("Error loading calendars:", error);
      addToast(
        <ToasterItem type="error" closeButton>
          {t("calendar.error.fetchCalendars")}
        </ToasterItem>,
      );
    } finally {
      setIsLoading(false);
    }
  }, [caldavService, t]);

  const toggleCalendarVisibility = useCallback((calendarUrl: string) => {
    setVisibleCalendarUrls((prev) => {
      const newVisible = new Set(prev);
      if (newVisible.has(calendarUrl)) {
        newVisible.delete(calendarUrl);
      } else {
        newVisible.add(calendarUrl);
      }
      // Persist: store the unchecked set (all known URLs minus visible)
      // Use ref to avoid stale closure over allCalendars
      const allUrls = allCalendarsRef.current.map((cal) => cal.url);
      const newUnchecked = new Set(allUrls.filter((url) => !newVisible.has(url)));
      saveUncheckedCalendarUrls(newUnchecked);
      return newVisible;
    });
  }, []);

  const createCalendar = useCallback(
    async (params: CalDavCalendarCreate): Promise<{ success: boolean; error?: string }> => {
      try {
        const result = await caldavService.createCalendar(params);
        if (result.success) {
          await refreshCalendars();
          return { success: true };
        }
        return {
          success: false,
          error: result.error || "Failed to create calendar",
        };
      } catch (error) {
        console.error("Error creating calendar:", error);
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error",
        };
      }
    },
    [caldavService, refreshCalendars],
  );

  const updateCalendar = useCallback(
    async (
      calendarUrl: string,
      params: CalDavCalendarUpdate,
    ): Promise<{ success: boolean; error?: string }> => {
      try {
        const result = await caldavService.updateCalendar(calendarUrl, params);
        if (result.success) {
          await refreshCalendars();
          return { success: true };
        }
        return {
          success: false,
          error: result.error || "Failed to update calendar",
        };
      } catch (error) {
        console.error("Error updating calendar:", error);
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error",
        };
      }
    },
    [caldavService, refreshCalendars],
  );

  // The calendar leaves the list and the visible set first, so a failed
  // refresh does not show it again.
  const removeDeletedCalendar = useCallback(
    async (calendarUrl: string) => {
      setAllCalendars((prev) => prev.filter((calendar) => calendar.url !== calendarUrl));
      setVisibleCalendarUrls((prev) => {
        const newSet = new Set(prev);
        newSet.delete(calendarUrl);
        return newSet;
      });
      await refreshCalendars();
    },
    [refreshCalendars],
  );

  const deleteCalendar = useCallback(
    async (calendarUrl: string): Promise<{ success: boolean; error?: string }> => {
      try {
        const result = await caldavService.deleteCalendar(calendarUrl);
        if (result.success) {
          await removeDeletedCalendar(calendarUrl);
          return { success: true };
        }
        // The calendar can have become sync-managed since the last fetch.
        // A refresh shows its delete action as disabled.
        if (result.status === 403) {
          await refreshCalendars();
        }
        return {
          success: false,
          error: result.error || "Failed to delete calendar",
        };
      } catch (error) {
        console.error("Error deleting calendar:", error);
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error",
        };
      }
    },
    [caldavService, refreshCalendars, removeDeletedCalendar],
  );

  const deleteMailboxCalendar = useCallback(
    async (
      calendarUrl: string,
      mailboxEmail: string,
    ): Promise<{ success: boolean; error?: string }> => {
      try {
        const calendarUri = decodeURIComponent(
          calendarUrl.replace(/\/$/, "").split("/").pop() ?? "",
        );
        await deleteMailboxCalendarApi(mailboxEmail, calendarUri);
      } catch (error) {
        console.error("Error deleting mailbox calendar:", error);
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error",
        };
      }
      await removeDeletedCalendar(calendarUrl);
      return { success: true };
    },
    [removeDeletedCalendar],
  );

  const shareCalendar = useCallback(
    async (
      calendarUrl: string,
      emails: string[],
      privilege: SharePrivilege = "read-write",
    ): Promise<{ success: boolean; error?: string; status?: number }> => {
      try {
        const result = await caldavService.shareCalendar({
          calendarUrl,
          sharees: emails.map((email) => ({
            href: `mailto:${email}`,
            privilege,
          })),
        });
        if (result.success) {
          return { success: true };
        }
        return {
          success: false,
          error: result.error || "Failed to share calendar",
          status: result.status,
        };
      } catch (error) {
        console.error("Error sharing calendar:", error);
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error",
        };
      }
    },
    [caldavService],
  );

  const movingRef = useRef(false);
  const moveCalendar = useCallback(
    async (
      calendarUrl: string,
      direction: "up" | "down",
    ): Promise<{ success: boolean; error?: string }> => {
      // Re-entry guard: a second click while the first move's PROPPATCHes
      // and refresh are still in flight would compute against stale state
      // (the closure captures orderedCalendars at call time) and could
      // swap the same pair twice or assign duplicate orders.
      if (movingRef.current) {
        return { success: false, error: "Move already in progress" };
      }
      movingRef.current = true;
      try {
        const list = [...orderedCalendars];
        const idx = list.findIndex((c) => c.url === calendarUrl);
        if (idx === -1) {
          return { success: false, error: "Calendar not found" };
        }
        const swapWith = direction === "up" ? idx - 1 : idx + 1;
        if (swapWith < 0 || swapWith >= list.length) {
          return { success: false, error: "Out of bounds" };
        }
        [list[idx], list[swapWith]] = [list[swapWith], list[idx]];

        // Rewrite the whole list as 0, 1, 2, and so on. Small contiguous
        // integers are the conventional values for this property, so
        // the order stays consistent if a user reorders the same
        // calendars in another CalDAV client. PROPPATCHes are skipped
        // for calendars whose value already matches, so a single swap
        // typically touches just the two moved siblings.
        const updates: Promise<{ success: boolean; error?: string }>[] = [];
        for (let i = 0; i < list.length; i++) {
          if (list[i].order !== i) {
            updates.push(caldavService.updateCalendar(list[i].url, { order: i }));
          }
        }
        try {
          const results = await Promise.all(updates);
          // updateCalendar reports CalDAV-level failures via `{success:
          // false}` rather than throwing, so Promise.all alone wouldn't
          // surface them. Bail out before refreshCalendars so the user
          // sees the error and the visible state isn't quietly stale.
          const failed = results.find((r) => !r.success);
          if (failed) {
            return {
              success: false,
              error: failed.error || "Failed to update calendar order",
            };
          }
          await refreshCalendars();
          return { success: true };
        } catch (error) {
          console.error("Error moving calendar:", error);
          return {
            success: false,
            error: error instanceof Error ? error.message : "Unknown error",
          };
        }
      } finally {
        movingRef.current = false;
      }
    },
    [caldavService, orderedCalendars, refreshCalendars],
  );

  const setCalendarHidden = useCallback(
    (calendarUrl: string, hidden: boolean) =>
      setCalendarHiddenAndRefresh(caldavService, refreshCalendars, calendarUrl, hidden),
    [caldavService, refreshCalendars],
  );

  const goToDate = useCallback((date: Date) => {
    if (calendarRef.current) {
      calendarRef.current.setOption("date", date);
    }
  }, []);

  // Note: refetchEvents is called in Scheduler component after updating the ref

  // Connect to CalDAV server on mount
  useEffect(() => {
    if (!userEmail) return;
    let isMounted = true;

    const connect = async () => {
      try {
        const result = await caldavService.connect({
          serverUrl: caldavServerUrl,
          userEmail,
        });
        if (isMounted && result.success) {
          setIsConnected(true);
          // Fetch calendars after successful connection
          const calendarsResult = await caldavService.fetchCalendars();
          if (isMounted && calendarsResult.success && calendarsResult.data) {
            setAllCalendars(calendarsResult.data);
            const unchecked = loadUncheckedCalendarUrls();
            setVisibleCalendarUrls(
              new Set(
                calendarsResult.data.map((cal) => cal.url).filter((url) => !unchecked.has(url)),
              ),
            );
          }
          setIsLoading(false);
        } else if (isMounted) {
          console.error("Failed to connect to CalDAV:", result.error);
          addToast(
            <ToasterItem type="error" closeButton>
              {t("calendar.error.connection")}
            </ToasterItem>,
          );
          setIsLoading(false);
        }
      } catch (error) {
        if (isMounted) {
          console.error("Error connecting to CalDAV:", error);
          addToast(
            <ToasterItem type="error" closeButton>
              {t("calendar.error.connection")}
            </ToasterItem>,
          );
          setIsLoading(false);
        }
      }
    };

    connect();

    // Cleanup: prevent state updates after unmount
    return () => {
      isMounted = false;
    };
    // Note: refreshCalendars is excluded to avoid dependency cycle
    // The initial fetch is done inline in this effect
  }, [caldavService, userEmail]);

  const value: CalendarContextType = {
    calendarRef,
    caldavService,
    adapter,
    davCalendars,
    orderedCalendars,
    hiddenCalendars,
    visibleCalendarUrls,
    isLoading,
    isConnected,
    currentDate,
    setCurrentDate,
    selectedDate,
    setSelectedDate,
    refreshCalendars,
    toggleCalendarVisibility,
    createCalendar,
    updateCalendar,
    deleteCalendar,
    deleteMailboxCalendar,
    shareCalendar,
    moveCalendar,
    setCalendarHidden,
    goToDate,
  };

  return <CalendarContext.Provider value={value}>{children}</CalendarContext.Provider>;
};
