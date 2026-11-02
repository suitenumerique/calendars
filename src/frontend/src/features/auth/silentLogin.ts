import { baseApiUrl } from "@/features/api/utils";

// The pending marker is per tab, so it uses sessionStorage.
// The cooldown applies to all tabs, so it uses localStorage.
const SILENT_LOGIN_RETRY_KEY = "calendars_silent-login-retry";
const SILENT_LOGIN_PENDING_KEY = "calendars_silent-login-pending";
const SILENT_LOGIN_RETRY_INTERVAL = 30 * 1000;

const hasRetryCooldownElapsed = () => {
  const nextRetryTime = localStorage.getItem(SILENT_LOGIN_RETRY_KEY);
  if (!nextRetryTime) {
    return true;
  }
  return Date.now() > Number(nextRetryTime);
};

const startCooldown = () => {
  localStorage.setItem(SILENT_LOGIN_RETRY_KEY, String(Date.now() + SILENT_LOGIN_RETRY_INTERVAL));
};

/** Clear the pending attempt of this tab after login. Keep the shared cooldown. */
export const clearPendingSilentLogin = () => {
  try {
    sessionStorage.removeItem(SILENT_LOGIN_PENDING_KEY);
  } catch {
    // Ignore storage errors.
  }
};

/**
 * Start a silent login, or clear a pending attempt. Call it only for an anonymous visitor.
 *
 * Sends silent=true and the current URL as returnTo to the backend.
 * The backend then asks the provider for prompt=none.
 * Returns true if the redirect starts.
 */
export const attemptSilentLogin = () => {
  // The app refused this user. The provider session stays active, so a retry starts a loop.
  const hasAuthError = new URLSearchParams(window.location.search).has("auth_error");

  try {
    // The earlier attempt did not log the visitor in.
    // End it and restart the cooldown, so the app does not retry at once.
    if (sessionStorage.getItem(SILENT_LOGIN_PENDING_KEY)) {
      sessionStorage.removeItem(SILENT_LOGIN_PENDING_KEY);
      startCooldown();
      return false;
    }

    if (!hasRetryCooldownElapsed() || hasAuthError) {
      return false;
    }

    startCooldown();
    sessionStorage.setItem(SILENT_LOGIN_PENDING_KEY, "1");
  } catch {
    // Without saved retry state, do not start a silent login.
    return false;
  }

  const url = new URL("authenticate/", baseApiUrl());
  url.searchParams.set("silent", "true");
  url.searchParams.set("returnTo", window.location.href);
  window.location.replace(url.href);
  return true;
};
