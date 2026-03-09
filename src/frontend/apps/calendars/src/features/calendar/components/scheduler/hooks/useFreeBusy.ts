import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
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
  const queryClient = useQueryClient();

  // Stable key: sort attendees so order doesn't trigger refetch
  const attendeesKey = useMemo(
    () => [...attendees].sort().join(","),
    [attendees],
  );
  const dateKey = date.toISOString().slice(0, 10);

  const queryKey = ["freebusy", attendeesKey, organizerEmail, dateKey];

  const query = useQuery({
    queryKey,
    queryFn: async (): Promise<FreeBusyResponse[]> => {
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

      if (result.success && result.data) {
        return result.data;
      }
      throw new Error(result.error ?? "Failed to query availability");
    },
    enabled: enabled && attendees.length > 0,
    retry: false,
  });

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey });
  }, [queryClient, queryKey]);

  return {
    data: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    refresh,
  };
}
