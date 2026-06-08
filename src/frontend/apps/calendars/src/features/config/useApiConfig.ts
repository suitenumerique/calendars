import { useQuery } from "@tanstack/react-query";
import { fetchAPI } from "@/features/api/fetchApi";
import { ApiConfig } from "@/features/api/types";

export function useApiConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const response = await fetchAPI("config/");
      return (await response.json()) as ApiConfig;
    },
    staleTime: 1000,
  });
}
