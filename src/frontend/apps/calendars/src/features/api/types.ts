export interface ApiConfig {
  FRONTEND_THEME?: string;
  FRONTEND_LAGAUFRE_ENABLED?: boolean;
  FRONTEND_LAGAUFRE_WIDGET_PATH?: string;
  FRONTEND_LAGAUFRE_WIDGET_API_URL?: string;
  FRONTEND_FEEDBACK_BUTTON_SHOW?: boolean;
  FRONTEND_FEEDBACK_BUTTON_IDLE?: boolean;
  FRONTEND_FEEDBACK_ITEMS?: Record<string, { url: string }>;
  FRONTEND_MORE_LINK?: string;
  FRONTEND_FEEDBACK_MESSAGES_WIDGET_ENABLED?: boolean;
  FRONTEND_FEEDBACK_MESSAGES_WIDGET_API_URL?: string;
  FRONTEND_FEEDBACK_MESSAGES_WIDGET_PATH?: string;
  FRONTEND_FEEDBACK_MESSAGES_WIDGET_CHANNEL?: string;
  FRONTEND_MEET_BASE_URL?: string;
  FEATURE_ADMIN_CHANNELS?: boolean;
  FEATURE_ADMIN_AVAILABILITIES?: boolean;
  FEATURE_ADMIN_RESOURCES?: boolean;
  theme_customization?: ThemeCustomization;
}

export interface UserFilters {
  [key: string]: unknown;
}

export interface ThemeCustomization {
  footer?: LocalizedRecord;
  [key: string]: LocalizedRecord | unknown;
}

export interface LocalizedRecord {
  default?: Record<string, unknown>;
  [languageCode: string]: Record<string, unknown> | undefined;
}

