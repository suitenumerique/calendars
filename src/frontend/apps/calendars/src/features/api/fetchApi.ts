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

export type fetchAPIOptions = Record<string, never>;

export const fetchAPI = async (
  input: string,
  init?: RequestInit & { params?: Record<string, string | number> },
) => {
  const apiUrl = new URL(`${baseApiUrl("1.0")}${input}`);
  if (init?.params) {
    Object.entries(init.params).forEach(([key, value]) => {
      apiUrl.searchParams.set(key, String(value));
    });
  }
  const csrfToken = getCSRFToken();

  const response = await fetch(apiUrl, {
    ...init,
    credentials: "include",
    headers: {
      ...init?.headers,
      "Content-Type": "application/json",
      ...(csrfToken && { "X-CSRFToken": csrfToken }),
    },
  });

  if (response.ok) {
    return response;
  }

  const data = await response.text();

  if (isJson(data)) {
    throw new APIError(response.status, JSON.parse(data));
  }

  throw new APIError(response.status);
};
