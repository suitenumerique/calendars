// Web API polyfills. Must be the first import of main.tsx: ES imports are
// hoisted, so inline statements in main.tsx would only run after every other
// module has evaluated. core-js (vite plugin-legacy) does not cover Web APIs.

// crypto.randomUUID: Chrome 109 exposes it only in secure contexts; ANCT
// instances reached over plain http don't have it. Several services call it
// when creating calendars and events.
if (typeof crypto !== "undefined" && typeof crypto.randomUUID !== "function") {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (crypto as any).randomUUID = (): string => {
    // RFC 4122 v4 via getRandomValues (available even when randomUUID is not)
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  };
}

export {};
