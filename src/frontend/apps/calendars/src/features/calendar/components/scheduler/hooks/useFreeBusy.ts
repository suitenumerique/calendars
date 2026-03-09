import { useState, useCallback, useRef, useEffect } from "react";
import type { FreeBusyResponse } from "../../../services/dav/types/caldav-service";
import type { CalDavService } from "../../../services/dav/CalDavService";

interface UseFreeBusyOptions {
  caldavService: CalDavService;
  attendees: string[];
  organizerEmail?: string;
  date: Date;
  enabled: boolean;
}

interface UseFreeBusyResult {
  data: FreeBusyResponse[];
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * Hook to query freebusy data for a list of attendees on a given date.
 * Automatically re-queries when attendees or date change.
 */
export function useFreeBusy({
  caldavService,
  attendees,
  organizerEmail,
  date,
  enabled,
}: UseFreeBusyOptions): UseFreeBusyResult {
  const [data, setData] = useState<FreeBusyResponse[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef(0);

  const fetchFreeBusy = useCallback(async () => {
    if (!enabled || attendees.length === 0) {
      setData([]);
      return;
    }

    const requestId = ++abortRef.current;
    setIsLoading(true);
    setError(null);

    // Query for the full day
    const start = new Date(date);
    start.setHours(0, 0, 0, 0);
    const end = new Date(date);
    end.setHours(23, 59, 59, 999);

    const result = await caldavService.queryFreeBusy({
      attendees,
      timeRange: { start, end },
      organizer: organizerEmail
        ? { email: organizerEmail, name: organizerEmail.split("@")[0] }
        : undefined,
    });

    // Ignore if a newer request was started
    if (requestId !== abortRef.current) return;

    if (result.success && result.data) {
      setData(result.data);
    } else {
      setError(result.error ?? "Failed to query availability");
      setData([]);
    }
    setIsLoading(false);
  }, [caldavService, attendees, organizerEmail, date, enabled]);

  // Auto-fetch when deps change
  useEffect(() => {
    fetchFreeBusy();
  }, [fetchFreeBusy]);

  return { data, isLoading, error, refresh: fetchFreeBusy };
}
