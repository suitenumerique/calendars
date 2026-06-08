import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAPI } from "@/features/api/fetchApi";

export interface UserSearchResult {
  id: string;
  email: string;
  full_name: string;
}

interface PaginatedResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: UserSearchResult[];
}

const DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 3;

function useDebouncedValue(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export const useUserSearch = (query: string) => {
  const debouncedQuery = useDebouncedValue(query.trim(), DEBOUNCE_MS);

  return useQuery({
    queryKey: ["users", "search", debouncedQuery],
    queryFn: async () => {
      const response = await fetchAPI("users/", {
        params: { q: debouncedQuery },
      });
      const data = (await response.json()) as PaginatedResponse;
      return data.results;
    },
    enabled: debouncedQuery.length >= MIN_QUERY_LENGTH,
  });
};
