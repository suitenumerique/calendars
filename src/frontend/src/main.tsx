// Polyfill crypto.randomUUID for insecure contexts (http) on Chromium 109.
// Chrome 109 supports crypto.randomUUID only in secure contexts; ANCT
// instances behind http proxies or on Windows 7 may hit this. The app calls
// crypto.randomUUID() in CalDavService:300,913, EventCalendarAdapter:421, etc.
// Guard once at entry so every call site is safe without per-site checks.
if (typeof crypto !== "undefined" && typeof crypto.randomUUID !== "function") {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (crypto as any).randomUUID = (): string => {
    // RFC4122 v4 via crypto.getRandomValues (available even when randomUUID is not)
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  };
}

import "./styles/globals.scss";
import "./features/i18n/initI18n";

import { createRoot } from "react-dom/client";
import {
  createRouter,
  parseSearchWith,
  RouterProvider,
  stringifySearchWith,
} from "@tanstack/react-router";
import { routeTree } from "./routes.gen";

// Default TSR encoding JSON-wraps every search value (`?key=1` → `?key=%221%22`).
// The rest of the app builds URLs via `URLSearchParams.toString()` and the
// backend expects plain values, so we plug identity parsers to keep both sides
// aligned — values stay as raw strings on the way out and on the way back.
const router = createRouter({
  routeTree,
  scrollRestoration: false,
  defaultPreload: false,
  parseSearch: parseSearchWith((value) => value),
  stringifySearch: stringifySearchWith((value) => (value == null ? "" : String(value))),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const container = document.getElementById("root");
if (!container) throw new Error("#root element not found in index.html");

createRoot(container).render(<RouterProvider router={router} />);
