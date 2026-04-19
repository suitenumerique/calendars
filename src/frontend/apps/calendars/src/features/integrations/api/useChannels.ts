import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { fetchAPI } from "@/features/api/fetchApi";
import type {
  Channel,
  ChannelCreateRequest,
  ChannelScopeValue,
  ChannelWithToken,
} from "../types";

const CHANNELS_QUERY_KEY = ["channels"];

async function fetchChannels(): Promise<Channel[]> {
  const response = await fetchAPI("channels/");
  return response.json();
}

async function createChannel(
  data: ChannelCreateRequest,
): Promise<ChannelWithToken> {
  const response = await fetchAPI("channels/", {
    method: "POST",
    body: JSON.stringify(data),
  });
  return response.json();
}

async function deleteChannel(id: string): Promise<void> {
  await fetchAPI(`channels/${id}/`, {
    method: "DELETE",
  });
}

async function regenerateToken(
  id: string,
): Promise<ChannelWithToken> {
  const response = await fetchAPI(
    `channels/${id}/regenerate-token/`,
    { method: "POST" },
  );
  return response.json();
}

type ChannelUpdate = {
  name?: string;
  is_active?: boolean;
  scopes?: ChannelScopeValue[];
};

async function updateChannel(
  id: string,
  patch: ChannelUpdate,
): Promise<Channel> {
  const response = await fetchAPI(`channels/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  return response.json();
}

export const useChannels = () => {
  return useQuery({
    queryKey: CHANNELS_QUERY_KEY,
    queryFn: fetchChannels,
  });
};

export const useCreateChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: CHANNELS_QUERY_KEY,
      });
    },
  });
};

export const useDeleteChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteChannel,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: CHANNELS_QUERY_KEY,
      });
    },
  });
};

export const useRegenerateToken = () => {
  return useMutation({
    mutationFn: regenerateToken,
  });
};

export const useUpdateChannel = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      id,
      ...patch
    }: { id: string } & ChannelUpdate) =>
      updateChannel(id, patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: CHANNELS_QUERY_KEY,
      });
    },
  });
};
