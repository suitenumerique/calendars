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
