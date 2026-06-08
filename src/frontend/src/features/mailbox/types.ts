export type MailboxRole = "viewer" | "editor" | "sender" | "admin";

export interface Mailbox {
  email: string;
  id: string;
  name: string;
  role: MailboxRole;
  users: { email: string; role: MailboxRole }[];
}

export interface MailboxCalendarInfo {
  mailbox_email: string;
  calendar_path: string;
  role: MailboxRole;
}

export interface MailboxSyncResult {
  available_mailboxes: Mailbox[];
  active_mailbox_calendars: MailboxCalendarInfo[];
}
