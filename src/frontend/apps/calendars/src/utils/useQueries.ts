import { UseQueryOptions } from "@tanstack/react-query";

export type HookUseQueryOptions<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;

