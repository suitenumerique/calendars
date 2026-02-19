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
import { caldavServerUrl, headers, fetchOptions } from "../utils/DavClient";
import type {
  CalDavCalendar,
  CalDavCalendarCreate,
} from "../services/dav/types/caldav-service";
import type { CalendarApi } from "../components/scheduler/types";
import { createCalendarApi } from "../api";
import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";

const HIDDEN_CALENDARS_KEY = "calendar-hidden-urls";

const loadHiddenUrls = (): Set<string> => {
  try {
    const stored = localStorage.getItem(HIDDEN_CALENDARS_KEY);
    if (stored) {
      return new Set(JSON.parse(stored) as string[]);
    }
  } catch {
    // Ignore parse errors
  }
  return new Set();
};

const saveHiddenUrls = (hiddenUrls: Set<string>) => {
  try {
    localStorage.setItem(
      HIDDEN_CALENDARS_KEY,
      JSON.stringify([...hiddenUrls]),
    );
  } catch {
    // Ignore storage errors
  }
};

export interface CalendarContextType {
  calendarRef: React.RefObject<CalendarApi | null>;
  caldavService: CalDavService;
  adapter: EventCalendarAdapter;
  davCalendars: CalDavCalendar[];
  ownedCalendars: CalDavCalendar[];
  sharedCalendars: CalDavCalendar[];
  visibleCalendarUrls: Set<string>;
  isLoading: boolean;
  isConnected: boolean;
  currentDate: Date;
  setCurrentDate: (date: Date) => void;
  selectedDate: Date;
  setSelectedDate: (date: Date) => void;
  refreshCalendars: () => Promise<void>;
  toggleCalendarVisibility: (calendarUrl: string) => void;
  createCalendar: (
    params: CalDavCalendarCreate,
  ) => Promise<{ success: boolean; error?: string }>;
  updateCalendar: (
    calendarUrl: string,
    params: { displayName?: string; color?: string; description?: string },
  ) => Promise<{ success: boolean; error?: string }>;
  deleteCalendar: (
    calendarUrl: string,
  ) => Promise<{ success: boolean; error?: string }>;
  shareCalendar: (
    calendarUrl: string,
    email: string,
  ) => Promise<{ success: boolean; error?: string }>;
  goToDate: (date: Date) => void;
}

const CalendarContext = createContext<CalendarContextType | undefined>(
  undefined,
);

export const useCalendarContext = () => {
  const context = useContext(CalendarContext);
  if (!context) {
    throw new Error(
      "useCalendarContext must be used within a CalendarContextProvider",
    );
  }
  return context;
};

interface CalendarContextProviderProps {
  children: ReactNode;
}

export const CalendarContextProvider = ({
  children,
}: CalendarContextProviderProps) => {
  const { t } = useTranslation();
  const calendarRef = useRef<CalendarApi | null>(null);
  const caldavService = useMemo(() => new CalDavService(), []);
  const adapter = useMemo(() => new EventCalendarAdapter(), []);
  const [davCalendars, setDavCalendars] = useState<CalDavCalendar[]>([]);
  const davCalendarsRef = useRef<CalDavCalendar[]>([]);
  davCalendarsRef.current = davCalendars;
  const [visibleCalendarUrls, setVisibleCalendarUrls] = useState<Set<string>>(
    new Set(),
  );
  const [isLoading, setIsLoading] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [currentDate, setCurrentDate] = useState<Date>(new Date());
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());

  const { ownedCalendars, sharedCalendars } = useMemo(() => {
    const homeUrl = caldavService.getAccount()?.homeUrl;
    if (!homeUrl) {
      return { ownedCalendars: davCalendars, sharedCalendars: [] };
    }
    const owned: CalDavCalendar[] = [];
    const shared: CalDavCalendar[] = [];
    for (const cal of davCalendars) {
      if (cal.url.startsWith(homeUrl)) {
        owned.push(cal);
      } else {
        shared.push(cal);
      }
    }
    return { ownedCalendars: owned, sharedCalendars: shared };
  }, [davCalendars, caldavService]);

  const refreshCalendars = useCallback(async () => {
    try {
      setIsLoading(true);
      const result = await caldavService.fetchCalendars();
      if (result.success && result.data) {
        setDavCalendars(result.data);
        // Compute visible = all minus hidden (new calendars default to visible)
        const hidden = loadHiddenUrls();
        setVisibleCalendarUrls(
          new Set(result.data.map((cal) => cal.url).filter((url) => !hidden.has(url))),
        );
      } else {
        console.error("Error fetching calendars:", result.error);
        addToast(
          <ToasterItem type="error" closeButton>
            {t("calendar.error.fetchCalendars")}
          </ToasterItem>,
        );
        setDavCalendars([]);
        setVisibleCalendarUrls(new Set());
      }
    } catch (error) {
      console.error("Error loading calendars:", error);
      addToast(
        <ToasterItem type="error" closeButton>
          {t("calendar.error.fetchCalendars")}
        </ToasterItem>,
      );
      setDavCalendars([]);
      setVisibleCalendarUrls(new Set());
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
      // Persist: store the hidden set (all known URLs minus visible)
      // Use ref to avoid stale closure over davCalendars
      const allUrls = davCalendarsRef.current.map((cal) => cal.url);
      const newHidden = new Set(allUrls.filter((url) => !newVisible.has(url)));
      saveHiddenUrls(newHidden);
      return newVisible;
    });
  }, []);

  const createCalendar = useCallback(
    async (
      params: CalDavCalendarCreate,
    ): Promise<{ success: boolean; error?: string }> => {
      try {
        // Use Django API to create calendar (CalDAV only)
        await createCalendarApi({
          name: params.displayName,
          color: params.color,
          description: params.description,
        });
        // Refresh CalDAV calendars list to show the new calendar
        await refreshCalendars();
        return { success: true };
      } catch (error) {
        console.error("Error creating calendar:", error);
        return {
          success: false,
          error: error instanceof Error ? error.message : "Unknown error",
        };
      }
    },
    [refreshCalendars],
  );

  const updateCalendar = useCallback(
    async (
      calendarUrl: string,
      params: { displayName?: string; color?: string; description?: string },
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

  const deleteCalendar = useCallback(
    async (
      calendarUrl: string,
    ): Promise<{ success: boolean; error?: string }> => {
      try {
        const result = await caldavService.deleteCalendar(calendarUrl);
        if (result.success) {
          // Remove from visible calendars
          setVisibleCalendarUrls((prev) => {
            const newSet = new Set(prev);
            newSet.delete(calendarUrl);
            return newSet;
          });
          await refreshCalendars();
          return { success: true };
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
    [caldavService, refreshCalendars],
  );

  const shareCalendar = useCallback(
    async (
      calendarUrl: string,
      email: string,
    ): Promise<{ success: boolean; error?: string }> => {
      try {
        const result = await caldavService.shareCalendar({
          calendarUrl,
          sharees: [
            {
              href: `mailto:${email}`,
              privilege: "read-write", // Same rights as principal
            },
          ],
        });
        if (result.success) {
          return { success: true };
        }
        return {
          success: false,
          error: result.error || "Failed to share calendar",
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

  const goToDate = useCallback((date: Date) => {
    if (calendarRef.current) {
      calendarRef.current.setOption("date", date);
    }
  }, []);

  // Note: refetchEvents is called in Scheduler component after updating the ref

  // Connect to CalDAV server on mount
  useEffect(() => {
    let isMounted = true;

    const connect = async () => {
      try {
        const result = await caldavService.connect({
          serverUrl: caldavServerUrl,
          headers,
          fetchOptions,
        });
        if (isMounted && result.success) {
          setIsConnected(true);
          // Fetch calendars after successful connection
          const calendarsResult = await caldavService.fetchCalendars();
          if (isMounted && calendarsResult.success && calendarsResult.data) {
            setDavCalendars(calendarsResult.data);
            const hidden = loadHiddenUrls();
            setVisibleCalendarUrls(
              new Set(
                calendarsResult.data
                  .map((cal) => cal.url)
                  .filter((url) => !hidden.has(url)),
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
  }, [caldavService]);

  const value: CalendarContextType = {
    calendarRef,
    caldavService,
    adapter,
    davCalendars,
    ownedCalendars,
    sharedCalendars,
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
    shareCalendar,
    goToDate,
  };

  return (
    <CalendarContext.Provider value={value}>
      {children}
    </CalendarContext.Provider>
  );
};
