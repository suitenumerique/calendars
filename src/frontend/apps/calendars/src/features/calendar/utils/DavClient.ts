/**
 * CalDAV client configuration utilities
 *
 * Provides centralized configuration for CalDAV server connections.
 * Used by CalendarContext to initialize CalDavService.
 */

import { getOrigin } from "@/features/api/utils";

export const caldavServerUrl = `${getOrigin()}/caldav/`;

// Marks the request as coming from the web frontend. The Django CalDAV proxy
// uses this to suppress the `WWW-Authenticate: Basic` header on 401 responses,
// so browsers don't show the native Basic auth popup when the session expires.
export const headers = {
  "Content-Type": "application/xml",
  "X-LS-Client": "web",
};

export const fetchOptions = {
  credentials: "include" as RequestCredentials,
  headers: {
    "Content-Type": "application/xml",
    "X-LS-Client": "web",
  },
};