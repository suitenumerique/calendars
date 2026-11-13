import type { IcsAttendee } from "ts-ics";
import type { UserSearchResult } from "@/features/users/hooks/useUserSearch";

/**
 * Filter search results to exclude already-added attendees
 * and the organizer email.
 */
export function filterSuggestions(
  searchResults: UserSearchResult[],
  attendees: IcsAttendee[],
  organizerEmail?: string,
): UserSearchResult[] {
  return searchResults.filter((user) => {
    const email = user.email?.toLowerCase();
    if (!email) return false;
    if (attendees.some((a) => a.email.toLowerCase() === email)) return false;
    if (organizerEmail && email === organizerEmail.toLowerCase()) return false;
    return true;
  });
}

export const isValidEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

interface ParsedAttendee {
  email: string;
  cn?: string;
}

interface ParsedAttendeeList {
  /** Valid addresses, in lowercase, without duplicates. */
  attendees: ParsedAttendee[];
  /** Tokens that are not a valid address, as the user wrote them. */
  invalid: string[];
}

// A quoted name can contain a separator, for example "Doe, Jane" <jane@x.org>.
const LIST_ENTRY = /(?:"[^"]*"|[^,;\n\r\t])+/g;
const NAMED_ADDRESS = /([^<>]*)<([^<>]*)>/g;

const splitWords = (text: string): string[] => text.match(/(?:"[^"]*"|\S)+/g) ?? [];

// A fully quoted address before `<` is a name, as in `'jane@x.org' <jane@x.org>`.
const isPlainAddress = (word: string): boolean => isValidEmail(word) && !/^(["']).*\1$/.test(word);

/**
 * Parse a list of email addresses.
 * The separators are the comma, the semicolon, the newline and the tab.
 * Spaces also separate plain addresses.
 * An entry can have the form `Name <email@host>`.
 */
export function parseAttendeeList(text: string): ParsedAttendeeList {
  const attendees: ParsedAttendee[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();

  const add = (token: string, address: string, cn?: string) => {
    const email = address.trim().toLowerCase();
    if (!isValidEmail(email)) {
      invalid.push(token);
      return;
    }
    if (seen.has(email)) return;
    seen.add(email);
    attendees.push({ email, ...(cn && { cn }) });
  };

  const addPlain = (words: string[]) => words.forEach((word) => add(word, word));

  for (const entry of text.match(LIST_ENTRY) ?? []) {
    let end = 0;
    for (const match of entry.matchAll(NAMED_ADDRESS)) {
      // A malformed part before the match, as in `bad <broken <a@x.org>`.
      addPlain(splitWords(entry.slice(end, match.index)));

      const words = splitWords(match[1]);
      // The name starts after the last plain address, as in `a@x.org Jane <jane@x.org>`.
      let nameStart = words.length;
      while (nameStart > 0 && !isPlainAddress(words[nameStart - 1])) nameStart--;
      addPlain(words.slice(0, nameStart));

      const name = words.slice(nameStart).join(" ");
      const cn = name.replace(/^(["'])(.*)\1$/, "$2").trim();
      add(`${name} <${match[2]}>`.trim(), match[2], cn);
      end = match.index + match[0].length;
    }
    addPlain(splitWords(entry.slice(end)));
  }

  return { attendees, invalid };
}
