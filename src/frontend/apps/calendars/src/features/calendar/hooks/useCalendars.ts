/**
 * React Query hooks for calendar operations.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Channel,
  ChannelError,
  createICalFeedChannel,
  deleteChannel,
  getICalFeedChannel,
  GetICalFeedResult,
  startImportTask,
  pollImportTask,
  ImportEventsResult,
} from "../api";

/**
 * Result type for useICalFeedChannel hook.
 */
export interface UseICalFeedChannelResult {
  channel: Channel | null;
  channelError: ChannelError | null;
  isLoading: boolean;
  refetch: () => void;
}

/**
 * Hook to get the ical-feed channel for a calendar by CalDAV path.
 */
export const useICalFeedChannel = (
  caldavPath: string,
): UseICalFeedChannelResult => {
  const query = useQuery<GetICalFeedResult>({
    queryKey: ["ical-feed-channel", caldavPath],
    queryFn: () => getICalFeedChannel(caldavPath),
    enabled: !!caldavPath,
    retry: false,
  });

  let channel: Channel | null = null;
  let channelError: ChannelError | null = null;

  const result = query.data;
  if (result) {
    if (result.success) {
      channel = result.channel;
    } else {
      channelError = result.error;
    }
  }

  return {
    channel,
    channelError,
    isLoading: query.isLoading,
    refetch: query.refetch,
  };
};

/**
 * Hook to create an ical-feed channel.
 */
export const useCreateICalFeedChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createICalFeedChannel,
    onSuccess: (_data, params) => {
      void queryClient.invalidateQueries({
        queryKey: ["ical-feed-channel", params.caldavPath],
      });
    },
  });
};

/**
 * Hook to delete a channel by ID. Invalidates ical-feed queries.
 */
export const useDeleteICalFeedChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["ical-feed-channel"],
      });
    },
  });
};

/**
 * Hook to import events from an ICS file.
 */
export const useImportEvents = () => {
  return useMutation<
    ImportEventsResult,
    Error,
    { caldavPath: string; file: File }
  >({
    mutationFn: async ({ caldavPath, file }) => {
      const taskId = await startImportTask(caldavPath, file);
      return pollImportTask(taskId);
    },
  });
};
