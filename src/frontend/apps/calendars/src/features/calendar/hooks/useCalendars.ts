/**
 * React Query hooks for calendar operations.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Calendar,
  createCalendar,
  getCalendars,
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
    mutationFn: createCalendar,
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
