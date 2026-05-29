import { baseApiUrl, isJson } from "./utils";
import { APIError } from "./APIError";

/**
 * Retrieves the CSRF token from the document's cookies.
 *
 * @returns {string|null} The CSRF token if found in the cookies, or null if not present.
 */
function getCSRFToken() {
  return document.cookie
    .split(";")
    .filter((cookie) => cookie.trim().startsWith("csrftoken="))
    .map((cookie) => cookie.split("=")[1])
    .pop();
}

export const SESSION_STORAGE_REDIRECT_AFTER_LOGIN_URL =
  "redirect_after_login_url";

/**
 * Redirect to the login page, saving the current URL for post-login redirect.
 * Called on any 401 response to handle expired sessions.
 *
 * Idempotent — if several concurrent requests all return 401 (e.g. multiple
 * React Query refetches on window focus), only the first call actually
 * persists the URL and triggers navigation; later calls are no-ops so the
 * stored `redirect_after_login_url` doesn't get overwritten by whatever
 * the URL happens to be mid-navigation.
 */
let redirectInFlight = false;
export function redirectToLogin() {
  if (redirectInFlight) return;
  redirectInFlight = true;
  // Persisting the current URL is best-effort: Safari Private Browsing,
  // a full storage quota, or a `SecurityError` from a sandboxed context
  // can all throw here. Treat that as "we just won't restore the URL
  // after login" — never let it suppress the actual navigation, which
  // is what unsticks the session.
  try {
    sessionStorage.setItem(
      SESSION_STORAGE_REDIRECT_AFTER_LOGIN_URL,
      window.location.href,
    );
  } catch {
    // intentionally swallow — the redirect itself is what matters.
  }
  window.location.replace(new URL("authenticate/", baseApiUrl()).href);
}

export type fetchAPIOptions = Record<string, never>;

export const fetchAPI = async (
  input: string,
  init?: RequestInit & {
    params?: Record<string, string | number>;
    // Opt out of the default 401 → login redirect. Used by Auth.tsx's boot
    // probe so anonymous pages (homepage, error pages) don't redirect when
    // the user has no session.
    skipAuthRedirect?: boolean;
  },
) => {
  const apiUrl = new URL(`${baseApiUrl("1.0")}${input}`);
  if (init?.params) {
    Object.entries(init.params).forEach(([key, value]) => {
      apiUrl.searchParams.set(key, String(value));
    });
  }
  const csrfToken = getCSRFToken();
  const isFormData = init?.body instanceof FormData;

  const response = await fetch(apiUrl, {
    ...init,
    credentials: "include",
    headers: {
      ...init?.headers,
      ...(!isFormData && { "Content-Type": "application/json" }),
      ...(csrfToken && { "X-CSRFToken": csrfToken }),
    },
  });

  if (response.ok) {
    return response;
  }

  if (response.status === 401 && !init?.skipAuthRedirect) {
    redirectToLogin();
  }

  const data = await response.text();

  if (isJson(data)) {
    throw new APIError(response.status, JSON.parse(data));
  }

  throw new APIError(response.status);
};
