import { createContext, useContext, useRef, useMemo, useState, useEffect, useCallback, type ReactNode } from "react";
import { Calendar } from "@event-calendar/core";
import { CalDavService } from "../services/dav/CalDavService";
import { EventCalendarAdapter } from "../services/dav/EventCalendarAdapter";
import { caldavServerUrl, headers, fetchOptions } from "../utils/DavClient";
import type { CalDavCalendar, CalDavCalendarCreate } from "../services/dav/types/caldav-service";
import { createCalendarApi } from "../api";

export interface CalendarContextType {
  calendarRef: React.RefObject<Calendar | null>;
  caldavService: CalDavService;
  adapter: EventCalendarAdapter;
  davCalendars: CalDavCalendar[];
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
  updateCalendar: (calendarUrl: string, params: { displayName?: string; color?: string; description?: string }) => Promise<{ success: boolean; error?: string }>;
  deleteCalendar: (calendarUrl: string) => Promise<{ success: boolean; error?: string }>;
  shareCalendar: (calendarUrl: string, email: string) => Promise<{ success: boolean; error?: string }>;
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
  const calendarRef = useRef<Calendar | null>(null);
  const caldavService = useMemo(() => new CalDavService(), []);
  const adapter = useMemo(() => new EventCalendarAdapter(), []);
  const [davCalendars, setDavCalendars] = useState<CalDavCalendar[]>([]);
  const [visibleCalendarUrls, setVisibleCalendarUrls] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [currentDate, setCurrentDate] = useState<Date>(new Date());
  const [selectedDate, setSelectedDate] = useState<Date>(new Date());

  const refreshCalendars = useCallback(async () => {
    try {
      setIsLoading(true);
      const result = await caldavService.fetchCalendars();
      if (result.success && result.data) {
        setDavCalendars(result.data);
        // Initialize all calendars as visible
        setVisibleCalendarUrls(new Set(result.data.map(cal => cal.url)));
      } else {
        console.error("Error fetching calendars:", result.error);
        setDavCalendars([]);
        setVisibleCalendarUrls(new Set());
      }
    } catch (error) {
      console.error("Error loading calendars:", error);
      setDavCalendars([]);
      setVisibleCalendarUrls(new Set());
    } finally {
      setIsLoading(false);
    }
  }, [caldavService]);

  const toggleCalendarVisibility = useCallback((calendarUrl: string) => {
    setVisibleCalendarUrls(prev => {
      const newSet = new Set(prev);
      if (newSet.has(calendarUrl)) {
        newSet.delete(calendarUrl);
      } else {
        newSet.add(calendarUrl);
      }
      return newSet;
    });
  }, []);

  const createCalendar = useCallback(async (params: CalDavCalendarCreate): Promise<{ success: boolean; error?: string }> => {
    try {
      // Use Django API to create calendar (creates both CalDAV and Django records)
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
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }, [refreshCalendars]);

  const updateCalendar = useCallback(async (
    calendarUrl: string,
    params: { displayName?: string; color?: string; description?: string }
  ): Promise<{ success: boolean; error?: string }> => {
    try {
      const result = await caldavService.updateCalendar(calendarUrl, params);
      if (result.success) {
        await refreshCalendars();
        return { success: true };
      }
      return { success: false, error: result.error || 'Failed to update calendar' };
    } catch (error) {
      console.error("Error updating calendar:", error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }, [caldavService, refreshCalendars]);

  const deleteCalendar = useCallback(async (calendarUrl: string): Promise<{ success: boolean; error?: string }> => {
    try {
      const result = await caldavService.deleteCalendar(calendarUrl);
      if (result.success) {
        // Remove from visible calendars
        setVisibleCalendarUrls(prev => {
          const newSet = new Set(prev);
          newSet.delete(calendarUrl);
          return newSet;
        });
        await refreshCalendars();
        return { success: true };
      }
      return { success: false, error: result.error || 'Failed to delete calendar' };
    } catch (error) {
      console.error("Error deleting calendar:", error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }, [caldavService, refreshCalendars]);

  const shareCalendar = useCallback(async (
    calendarUrl: string,
    email: string
  ): Promise<{ success: boolean; error?: string }> => {
    try {
      const result = await caldavService.shareCalendar({
        calendarUrl,
        sharees: [{
          href: `mailto:${email}`,
          privilege: 'read-write', // Same rights as principal
        }],
      });
      if (result.success) {
        return { success: true };
      }
      return { success: false, error: result.error || 'Failed to share calendar' };
    } catch (error) {
      console.error("Error sharing calendar:", error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }, [caldavService]);

  const goToDate = useCallback((date: Date) => {
    if (calendarRef.current) {
      calendarRef.current.setOption('date', date);
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
            setVisibleCalendarUrls(new Set(calendarsResult.data.map(cal => cal.url)));
          }
          setIsLoading(false);
        } else if (isMounted) {
          console.error("Failed to connect to CalDAV:", result.error);
          setIsLoading(false);
        }
      } catch (error) {
        if (isMounted) {
          console.error("Error connecting to CalDAV:", error);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caldavService]);

  const value: CalendarContextType = {
    calendarRef,
    caldavService,
    adapter,
    davCalendars,
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

  return <CalendarContext.Provider value={value}>{children}</CalendarContext.Provider>;
};
