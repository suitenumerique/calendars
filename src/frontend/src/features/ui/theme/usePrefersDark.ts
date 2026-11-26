import { useSyncExternalStore } from "react";

const QUERY = "(prefers-color-scheme: dark)";

const subscribe = (onChange: () => void) => {
  if (!window.matchMedia) return () => {};
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
};

const getSnapshot = () => window.matchMedia?.(QUERY).matches ?? false;

export const usePrefersDark = () => useSyncExternalStore(subscribe, getSnapshot, () => false);
