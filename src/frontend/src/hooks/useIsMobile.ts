import { useSyncExternalStore } from "react";

export const MOBILE_BREAKPOINT = 768;

const MEDIA_QUERY = `(max-width: ${MOBILE_BREAKPOINT}px)`;

function subscribe(callback: () => void): () => void {
  const mql = window.matchMedia(MEDIA_QUERY);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getSnapshot(): boolean {
  return window.matchMedia(MEDIA_QUERY).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
