import { baseApiUrl } from "@/features/api/utils";

const SILENT_LOGIN_RETRY_KEY = "calendars_silent-login-retry";
const SILENT_LOGIN_RETRY_INTERVAL = 30 * 1000;

export const canAttemptSilentLogin = () => {
  try {
    const nextRetryTime = localStorage.getItem(SILENT_LOGIN_RETRY_KEY);
    if (!nextRetryTime) {
      return true;
    }
    return Date.now() > Number(nextRetryTime);
  } catch {
    return false;
  }
};

/**
 * Redirect to the OIDC provider with prompt=none, logging the visitor in if they
 * already have an SSO session and returning them here if they don't. Returns
 * whether the redirect was started.
 */
export const attemptSilentLogin = () => {
  // A user the app refuses is still authenticated at the provider, so retrying
  // would log them in and bounce them off again until the cooldown catches up.
  const hasAuthError = new URLSearchParams(window.location.search).has("auth_error");
  if (!canAttemptSilentLogin() || hasAuthError) {
    return false;
  }

  try {
    localStorage.setItem(SILENT_LOGIN_RETRY_KEY, String(Date.now() + SILENT_LOGIN_RETRY_INTERVAL));
  } catch {
    // The cooldown is what stops a redirect loop, so without it, don't go.
    return false;
  }

  const url = new URL("authenticate/", baseApiUrl());
  url.searchParams.set("silent", "true");
  url.searchParams.set("returnTo", window.location.href);
  window.location.replace(url.href);
  return true;
};
