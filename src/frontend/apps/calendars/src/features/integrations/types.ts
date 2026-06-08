export const CHANNEL_SCOPES = [
  "calendars:read",
  "calendars:write",
  "events:read",
  "events:write",
] as const;

export type ChannelScopeValue = (typeof CHANNEL_SCOPES)[number];

// Backend-enforced enum values. Keep these in sync with:
// - src/backend/core/api/serializers.py (ChannelCreateSerializer.type choices)
// - src/backend/core/enums.py (ChannelScopeLevel)
export const CHANNEL_TYPES = ["caldav", "ical-feed"] as const;
export type ChannelType = (typeof CHANNEL_TYPES)[number];

export const CHANNEL_SCOPE_LEVELS = ["global", "user", "calendar"] as const;
export type ChannelScopeLevel = (typeof CHANNEL_SCOPE_LEVELS)[number];

export type Channel = {
  id: string;
  name: string;
  type: ChannelType;
  scopes: ChannelScopeValue[];
  scope_level: ChannelScopeLevel;
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
  password: string;
};

export type ChannelCreateRequest = {
  name: string;
  type: ChannelType;
  scope_level: ChannelScopeLevel;
  scopes: ChannelScopeValue[];
  caldav_path?: string;
  calendar_name?: string;
};
