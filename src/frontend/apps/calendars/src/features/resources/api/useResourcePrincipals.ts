import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { propfind } from "tsdav";

import { getOrigin } from "@/features/api/utils";

import type { ResourceType } from "../types";

export type ResourcePrincipal = {
  id: string;
  name: string;
  email?: string;
  resourceType: ResourceType;
};

const RESOURCE_PRINCIPALS_KEY = ["resource-principals"];
const EMPTY_RESOURCES: ResourcePrincipal[] = [];

async function fetchResourcePrincipals(): Promise<ResourcePrincipal[]> {
  const caldavUrl = `${getOrigin()}/caldav/principals/resources/`;

  const response = await propfind({
    url: caldavUrl,
    props: {
      "d:displayname": {},
      "d:resourcetype": {},
      "c:calendar-user-type": {},
      "c:calendar-user-address-set": {},
    },
    depth: "1",
    headers: {},
    fetchOptions: { credentials: "include" as RequestCredentials },
  });

  const resources: ResourcePrincipal[] = [];

  for (const item of response) {
    // Skip the collection itself (depth=0 result)
    const href = item.href || "";
    if (!href || href.endsWith("/resources/") || href.endsWith("/resources")) {
      continue;
    }

    // Extract resource ID from path like /caldav/principals/resources/{uuid}/
    const parts = href.replace(/\/$/, "").split("/");
    const id = parts[parts.length - 1];
    if (!id) continue;

    const props = item.props || {};
    const displayName =
      props.displayname?._cdata ?? props.displayname ?? id;
    const rawCutype =
      props.calendarUserType || props["calendar-user-type"] || "ROOM";
    const calendarUserType: ResourceType =
      rawCutype === "ROOM" || rawCutype === "RESOURCE" ? rawCutype : "ROOM";

    // Extract email from calendar-user-address-set
    let email: string | undefined;
    const addressSet =
      props.calendarUserAddressSet || props["calendar-user-address-set"];
    if (addressSet) {
      const hrefValue = addressSet.href;
      const hrefs = Array.isArray(hrefValue) ? hrefValue : [hrefValue];
      for (const h of hrefs) {
        if (typeof h === "string" && h.startsWith("mailto:")) {
          email = h.replace("mailto:", "");
          break;
        }
      }
    }

    resources.push({
      id,
      name: typeof displayName === "string" ? displayName : id,
      email,
      resourceType: calendarUserType,
    });
  }

  return resources;
}

export const useResourcePrincipals = () => {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: RESOURCE_PRINCIPALS_KEY,
    queryFn: fetchResourcePrincipals,
    staleTime: 30_000,
  });

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: RESOURCE_PRINCIPALS_KEY,
    });
  }, [queryClient]);

  return {
    resources: query.data ?? EMPTY_RESOURCES,
    isLoading: query.isLoading,
    error: query.error,
    refresh,
  };
};
