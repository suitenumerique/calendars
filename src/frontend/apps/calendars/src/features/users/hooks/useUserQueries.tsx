import { useQuery } from "@tanstack/react-query";
import { HookUseQueryOptions } from "@/utils/useQueries";
import { fetchAPI } from "@/features/api/fetchApi";
import { User } from "@/features/users/types";
import { UserFilters } from "@/features/api/types";

export const useUsers = (
  filters?: UserFilters,
  options?: HookUseQueryOptions<User[]>
) => {
  return useQuery({
    ...options,
    queryKey: ["users", filters],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (filters) {
        Object.entries(filters).forEach(([key, value]) => {
          if (value !== undefined && value !== null) {
            params.append(key, String(value));
          }
        });
      }
      const response = await fetchAPI(`users/${params.toString() ? `?${params.toString()}` : ""}`);
      return (await response.json()) as User[];
    },
  });
};
