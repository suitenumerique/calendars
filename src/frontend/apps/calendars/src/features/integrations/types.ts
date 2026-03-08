export type ChannelRole = "reader" | "editor" | "admin";

export type Channel = {
  id: string;
  name: string;
  type: string;
  role: ChannelRole;
  caldav_path: string;
  url: string | null;
  user: string;
  organization: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  settings: Record<string, unknown>;
};

export type ChannelWithToken = Channel & {
  token: string;
};

export type ChannelCreateRequest = {
  name: string;
  type?: string;
  role?: ChannelRole;
  caldav_path?: string;
  calendar_name?: string;
};
