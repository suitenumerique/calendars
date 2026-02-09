/**
 * Event display rules — clean and deduplicate fields before rendering.
 *
 * Single entry point: cleanEventForDisplay()
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Prefixes stripped from the Location field (case-insensitive). */
const LOCATION_PREFIXES_TO_STRIP = [
  'Pour participer à la visioconférence, cliquez sur ce lien : ',
];

/**
 * Embedded conference block delimited by ~:~ markers.
 * Contains a video-conference URL. Providers inject this in descriptions.
 */
const CONFERENCE_BLOCK_RE =
  /-::~:~::~:~[:~]*::~:~::-\s*\n.*?(https:\/\/\S+).*?\n.*?-::~:~::~:~[:~]*::~:~::-/s;

const URL_RE = /https?:\/\/[^\s]+/i;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type EventDisplayFields = {
  description: string;
  location: string;
  url: string;
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Clean and deduplicate event fields for display.
 *
 * Applies in order:
 *  1. Trim whitespace on all fields
 *  2. Strip known prefixes from location
 *  3. Extract embedded conference URL from description → url (if url empty)
 *  4. Deduplicate: desc==location → empty desc,
 *     location==url → empty location, desc==url → empty desc
 */
export const cleanEventForDisplay = (
  raw: EventDisplayFields,
): EventDisplayFields => {
  let description = raw.description.trim();
  let location = stripLocationPrefixes(raw.location.trim());
  let url = raw.url.trim();

  // Extract embedded conference block from description
  if (!url) {
    const extracted = extractConferenceBlock(description);
    if (extracted.url) {
      description = extracted.description;
      url = extracted.url;
    }
  }

  // Deduplicate across fields
  if (description && description === location) description = '';
  if (location && location === url) location = '';
  if (description && description === url) description = '';

  return { description, location, url };
};

/**
 * Extract the first URL found anywhere in a string.
 */
export const extractUrl = (text: string): string | null => {
  const match = text.match(URL_RE);
  return match ? match[0] : null;
};

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

const stripLocationPrefixes = (value: string): string => {
  for (const prefix of LOCATION_PREFIXES_TO_STRIP) {
    if (value.toLowerCase().startsWith(prefix.toLowerCase())) {
      return value.slice(prefix.length).trim();
    }
  }
  return value;
};

const extractConferenceBlock = (
  text: string,
): { description: string; url: string | null } => {
  const match = text.match(CONFERENCE_BLOCK_RE);
  if (!match) return { description: text, url: null };
  return {
    description: text.replace(match[0], '').trim(),
    url: match[1] ?? null,
  };
};
