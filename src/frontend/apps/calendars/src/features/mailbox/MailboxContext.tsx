import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useMailboxSync } from "./useMailboxSync";
import type { Mailbox, MailboxCalendarInfo } from "./types";
import type { CalDavCalendar } from "@/features/calendar/services/dav/types/caldav-service";

export interface MailboxContextType {
  availableMailboxes: Mailbox[];
  activeMailboxCalendars: MailboxCalendarInfo[];
  /**
   * Check if a calendar is a mailbox calendar.
   * Uses the LS:calendar-owner-type DAV property when a calendar object
   * is provided, falling back to path matching for owner calendars.
   */
  isMailboxCalendar: (calendarUrl: string, calendar?: CalDavCalendar) => boolean;
  /**
   * Get the mailbox email for a calendar.
   * Uses activeMailboxCalendars path matching + ownerType detection.
   */
  getMailboxEmail: (calendarUrl: string, calendar?: CalDavCalendar) => string | undefined;
  isLoading: boolean;
}

const MailboxContext = createContext<MailboxContextType | undefined>(undefined);

export function useMailboxContext(): MailboxContextType {
  const context = useContext(MailboxContext);
  if (!context) {
    throw new Error(
      "useMailboxContext must be used within MailboxContextProvider",
    );
  }
  return context;
}

interface MailboxContextProviderProps {
  children: ReactNode;
}

export function MailboxContextProvider({
  children,
}: MailboxContextProviderProps) {
  const { data, isLoading } = useMailboxSync();

  const availableMailboxes = data?.available_mailboxes ?? [];
  const activeMailboxCalendars = data?.active_mailbox_calendars ?? [];

  // Map of owner calendar paths to mailbox emails (for owner's own view)
  const ownerPathMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const mc of activeMailboxCalendars) {
      map.set(mc.calendar_path, mc.mailbox_email);
      map.set(`/${mc.calendar_path}/`, mc.mailbox_email);
    }
    return map;
  }, [activeMailboxCalendars]);

  // Set of known mailbox emails for reverse lookup
  const mailboxEmails = useMemo(
    () => new Set(activeMailboxCalendars.map((mc) => mc.mailbox_email)),
    [activeMailboxCalendars],
  );

  const isMailboxCalendar = useMemo(
    () => (calendarUrl: string, calendar?: CalDavCalendar) => {
      // Primary: check DAV property (works for shared instances with any URI)
      if (calendar?.ownerType === "MAILBOX") return true;
      // Fallback: path matching for the owner's own calendar view
      for (const [path] of ownerPathMap) {
        if (calendarUrl.includes(path)) return true;
      }
      return false;
    },
    [ownerPathMap],
  );

  const getMailboxEmail = useMemo(
    () => (calendarUrl: string, calendar?: CalDavCalendar) => {
      // Primary: if ownerType is MAILBOX, extract the owner email from
      // the calendar URL path (calendars/users/{email}/...)
      if (calendar?.ownerType === "MAILBOX") {
        const match = calendarUrl.match(/calendars\/users\/([^/]+)\//);
        if (match) {
          const email = decodeURIComponent(match[1]);
          // If the URL user is a known mailbox, return it directly
          if (mailboxEmails.has(email)) return email;
        }
        // For shared instances, the URL contains the sharee's email,
        // not the mailbox email. Use activeMailboxCalendars to find it.
        // The ownerType confirms it's a mailbox; we need to match via
        // the backend's active_mailbox_calendars list.
        for (const mc of activeMailboxCalendars) {
          // The calendar's underlying calendar lives at the mailbox path
          if (calendarUrl.includes(mc.calendar_path)) return mc.mailbox_email;
        }
        // Can't determine which mailbox — don't guess
        return undefined;
      }
      // Fallback: path matching for the owner's own calendar view
      for (const [path, email] of ownerPathMap) {
        if (calendarUrl.includes(path)) return email;
      }
      return undefined;
    },
    [ownerPathMap, mailboxEmails, activeMailboxCalendars],
  );

  const value: MailboxContextType = {
    availableMailboxes,
    activeMailboxCalendars,
    isMailboxCalendar,
    getMailboxEmail,
    isLoading,
  };

  return (
    <MailboxContext.Provider value={value}>{children}</MailboxContext.Provider>
  );
}
