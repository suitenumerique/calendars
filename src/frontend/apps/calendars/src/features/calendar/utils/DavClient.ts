/**
 * CalDAV client configuration utilities
 *
 * Provides centralized configuration for CalDAV server connections.
 * Used by CalendarContext to initialize CalDavService.
 */

export const caldavServerUrl = `${process.env.NEXT_PUBLIC_API_ORIGIN}/api/v1.0/caldav/`;

export const headers = {
  "Content-Type": "application/xml",
};

export const fetchOptions = {
  credentials: "include" as RequestCredentials,
  headers: {
    "Content-Type": "application/xml",
  },
};