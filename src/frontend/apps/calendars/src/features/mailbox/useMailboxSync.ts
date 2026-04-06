import { useQuery } from "@tanstack/react-query";
import { useConfig } from "@/features/config/ConfigProvider";
import { fetchMailboxes } from "./api";
import type { MailboxSyncResult } from "./types";

const EMPTY_RESULT: MailboxSyncResult = {
  available_mailboxes: [],
  active_mailbox_calendars: [],
};

export function useMailboxSync() {
  const { config } = useConfig();
  const enabled = !!config?.FEATURE_MESSAGES_INTEGRATION;

  return useQuery({
    queryKey: ["mailbox-sync"],
    queryFn: fetchMailboxes,
    enabled,
    staleTime: 60_000,
    placeholderData: EMPTY_RESULT,
  });
}
