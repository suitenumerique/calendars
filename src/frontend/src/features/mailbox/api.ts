import { fetchAPI } from "@/features/api/fetchApi";

import type { MailboxSyncResult } from "./types";

export async function fetchMailboxes(): Promise<MailboxSyncResult> {
  const response = await fetchAPI("setup/mailboxes/");
  return response.json();
}

export async function setupCalendar(
  name: string,
  mailboxEmail?: string,
  color?: string,
): Promise<{
  calendar_path: string;
  principal_uri: string;
  mailbox_email?: string;
}> {
  const body: Record<string, string> = { name };
  if (mailboxEmail) body.mailbox_email = mailboxEmail;
  if (color) body.color = color;
  const response = await fetchAPI("setup/", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return response.json();
}

/**
 * Delete a MAILBOX-owned calendar for every mailbox user.
 *
 * Unlike a plain CalDAV DELETE (which only ever removes the caller's
 * own share), this reaches the real owner-branch delete via the
 * backend's internal API, so the calendar disappears for everyone.
 *
 * `calendarUri` is the URI the caller reads the calendar at under
 * their own principal — the last path segment of the calendar's URL.
 */
export async function deleteMailboxCalendar(
  mailboxEmail: string,
  calendarUri: string,
): Promise<void> {
  await fetchAPI("setup/", {
    method: "DELETE",
    body: JSON.stringify({ mailbox_email: mailboxEmail, calendar_uri: calendarUri }),
  });
}
