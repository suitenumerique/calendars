import { useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchAPI } from "@/features/api/fetchApi";
import type { Resource, ResourceCreateRequest } from "../types";

const RESOURCES_QUERY_KEY = ["resources"];

async function createResource(
  data: ResourceCreateRequest,
): Promise<Resource> {
  const response = await fetchAPI("resources/", {
    method: "POST",
    body: JSON.stringify(data),
  });
  return response.json();
}

async function deleteResource(id: string): Promise<void> {
  await fetchAPI(`resources/${id}/`, {
    method: "DELETE",
  });
}

export const useCreateResource = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createResource,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RESOURCES_QUERY_KEY });
    },
  });
};

export const useDeleteResource = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteResource,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RESOURCES_QUERY_KEY });
    },
  });
};
