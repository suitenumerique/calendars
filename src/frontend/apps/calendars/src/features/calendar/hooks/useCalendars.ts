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
  SubscriptionChannel,
  getSubscriptionChannels,
  createSubscriptionChannel,
  updateSubscriptionChannel,
  deleteSubscriptionChannel,
  reactivateSubscriptionChannel,
} from "../api";
import { SYNC_POLL_INTERVAL } from "../config";

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

// ============================================================================
// Subscription Channel Hooks
// ============================================================================

/**
 * Hook to get all subscription channels.
 */
export const useSubscriptionChannels = () => {
  return useQuery<SubscriptionChannel[]>({
    queryKey: ["subscription-channels"],
    queryFn: getSubscriptionChannels,
    refetchInterval: SYNC_POLL_INTERVAL,
  });
};

/**
 * Hook to create a subscription channel.
 */
export const useCreateSubscriptionChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createSubscriptionChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["subscription-channels"],
      });
    },
  });
};

/**
 * Hook to update a subscription channel.
 */
export const useUpdateSubscriptionChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      channelId,
      params,
    }: {
      channelId: string;
      params: { name?: string; sourceUrl?: string; color?: string };
    }) => updateSubscriptionChannel(channelId, params),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["subscription-channels"],
      });
    },
  });
};

/**
 * Hook to delete a subscription channel.
 */
export const useDeleteSubscriptionChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteSubscriptionChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["subscription-channels"],
      });
    },
  });
};

/**
 * Hook to reactivate a stopped subscription channel.
 */
export const useReactivateSubscriptionChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: reactivateSubscriptionChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["subscription-channels"],
      });
    },
  });
};
