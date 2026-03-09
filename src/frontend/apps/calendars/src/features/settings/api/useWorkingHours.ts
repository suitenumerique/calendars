import { useEffect, useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { CalDavService } from "@/features/calendar/services/dav/CalDavService";
import {
  caldavServerUrl,
  headers,
  fetchOptions,
} from "@/features/calendar/utils/DavClient";
import { useAuth } from "@/features/auth/Auth";

import {
  DEFAULT_AVAILABILITY,
  type AvailabilitySlots,
} from "../types";
import {
  slotsToVCalendar,
  vCalendarToSlots,
} from "../availability-ics";

const WORKING_HOURS_KEY = ["working-hours"];

export const useWorkingHours = () => {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const caldavService = useMemo(() => new CalDavService(), []);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;

    caldavService
      .connect({ serverUrl: caldavServerUrl, headers, fetchOptions })
      .then((result) => {
        if (!cancelled && result.success) {
          setIsConnected(true);
        }
      })
      .catch((err) => {
        console.error("Failed to connect to CalDAV:", err);
      });

    return () => {
      cancelled = true;
    };
  }, [caldavService, user]);

  const query = useQuery({
    queryKey: WORKING_HOURS_KEY,
    queryFn: async (): Promise<AvailabilitySlots> => {
      const result = await caldavService.getAvailability();
      if (
        !result.success ||
        typeof result.data !== "string" ||
        !result.data.includes("VAVAILABILITY")
      ) {
        return DEFAULT_AVAILABILITY;
      }
      const slots = vCalendarToSlots(result.data);
      return slots.length > 0 ? slots : DEFAULT_AVAILABILITY;
    },
    enabled: isConnected,
  });

  const mutation = useMutation({
    mutationFn: async (slots: AvailabilitySlots) => {
      const vcalendar = slotsToVCalendar(slots);
      const result = await caldavService.setAvailability(vcalendar);
      if (!result.success) {
        throw new Error(
          result.error ?? "Failed to save availability",
        );
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: WORKING_HOURS_KEY,
      });
    },
  });

  return {
    slots: query.data ?? DEFAULT_AVAILABILITY,
    isLoading: !isConnected || query.isLoading,
    save: mutation.mutateAsync,
    isSaving: mutation.isPending,
  };
};
