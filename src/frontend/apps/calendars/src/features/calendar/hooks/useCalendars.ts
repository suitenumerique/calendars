/**
 * React Query hooks for calendar operations.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Calendar,
  createCalendarApi,
  createSubscriptionToken,
  deleteSubscriptionToken,
  getCalendars,
  getSubscriptionToken,
  GetSubscriptionTokenResult,
  SubscriptionToken,
  SubscriptionTokenError,
  SubscriptionTokenParams,
  toggleCalendarVisibility,
} from "../api";

const CALENDARS_KEY = ["calendars"];

/**
 * Hook to fetch all calendars.
 */
export const useCalendars = () => {
  return useQuery<Calendar[]>({
    queryKey: CALENDARS_KEY,
    queryFn: getCalendars,
  });
};

/**
 * Hook to create a new calendar.
 */
export const useCreateCalendar = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createCalendarApi,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CALENDARS_KEY });
    },
  });
};

/**
 * Hook to toggle calendar visibility.
 */
export const useToggleCalendarVisibility = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: toggleCalendarVisibility,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: CALENDARS_KEY });
    },
  });
};

/**
 * Result type for useSubscriptionToken hook.
 */
export interface UseSubscriptionTokenResult {
  token: SubscriptionToken | null;
  tokenError: SubscriptionTokenError | null;
  isLoading: boolean;
  refetch: () => void;
}

/**
 * Hook to get subscription token for a calendar by CalDAV path.
 * Handles the result/error pattern from getSubscriptionToken.
 */
export const useSubscriptionToken = (caldavPath: string): UseSubscriptionTokenResult => {
  const query = useQuery<GetSubscriptionTokenResult>({
    queryKey: ["subscription-token", caldavPath],
    queryFn: () => getSubscriptionToken(caldavPath),
    enabled: !!caldavPath,
    retry: false,
  });

  // Extract token and error from the result using proper type narrowing
  const result = query.data;
  let token: SubscriptionToken | null = null;
  let tokenError: SubscriptionTokenError | null = null;

  if (result) {
    if (result.success) {
      token = result.token;
    } else {
      tokenError = result.error;
    }
  }

  return {
    token,
    tokenError,
    isLoading: query.isLoading,
    refetch: query.refetch,
  };
};

/**
 * Hook to create a subscription token.
 */
export const useCreateSubscriptionToken = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createSubscriptionToken,
    onSuccess: (_data, params: SubscriptionTokenParams) => {
      queryClient.invalidateQueries({
        queryKey: ["subscription-token", params.caldavPath],
      });
    },
  });
};

/**
 * Hook to delete (revoke) a subscription token.
 */
export const useDeleteSubscriptionToken = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteSubscriptionToken,
    onSuccess: (_data, caldavPath: string) => {
      queryClient.invalidateQueries({
        queryKey: ["subscription-token", caldavPath],
      });
    },
  });
};
