import { filterSuggestions, isValidEmail } from "../attendees-utils";
import type { UserSearchResult } from "@/features/users/hooks/useUserSearch";
import type { IcsAttendee } from "ts-ics";

describe("attendees-utils", () => {
  describe("isValidEmail", () => {
    it("accepts a valid email", () => {
      expect(isValidEmail("user@example.com")).toBe(true);
    });

    it("rejects an empty string", () => {
      expect(isValidEmail("")).toBe(false);
    });

    it("rejects a string without @", () => {
      expect(isValidEmail("not-an-email")).toBe(false);
    });

    it("rejects a string without domain", () => {
      expect(isValidEmail("user@")).toBe(false);
    });

    it("rejects a string with spaces", () => {
      expect(isValidEmail("user @example.com")).toBe(false);
    });
  });

  describe("filterSuggestions", () => {
    const makeUser = (
      email: string,
      name = "Test User",
    ): UserSearchResult => ({
      id: email,
      email,
      full_name: name,
    });

    const makeAttendee = (email: string): IcsAttendee => ({
      email,
      partstat: "NEEDS-ACTION",
      rsvp: true,
      role: "REQ-PARTICIPANT",
    });

    it("returns all suggestions when no attendees or organizer", () => {
      const results = [
        makeUser("alice@org.com", "Alice"),
        makeUser("bob@org.com", "Bob"),
      ];
      expect(filterSuggestions(results, [])).toEqual(results);
    });

    it("filters out already-added attendees", () => {
      const results = [
        makeUser("alice@org.com"),
        makeUser("bob@org.com"),
        makeUser("carol@org.com"),
      ];
      const attendees = [makeAttendee("alice@org.com")];
      const filtered = filterSuggestions(results, attendees);
      expect(filtered).toHaveLength(2);
      expect(filtered.map((u) => u.email)).toEqual([
        "bob@org.com",
        "carol@org.com",
      ]);
    });

    it("filters case-insensitively", () => {
      const results = [makeUser("Alice@Org.com")];
      const attendees = [makeAttendee("alice@org.com")];
      expect(filterSuggestions(results, attendees)).toHaveLength(0);
    });

    it("filters out the organizer email", () => {
      const results = [
        makeUser("organizer@org.com"),
        makeUser("other@org.com"),
      ];
      const filtered = filterSuggestions(
        results,
        [],
        "organizer@org.com",
      );
      expect(filtered).toHaveLength(1);
      expect(filtered[0].email).toBe("other@org.com");
    });

    it("filters organizer case-insensitively", () => {
      const results = [makeUser("Organizer@Org.COM")];
      const filtered = filterSuggestions(
        results,
        [],
        "organizer@org.com",
      );
      expect(filtered).toHaveLength(0);
    });

    it("filters both attendees and organizer together", () => {
      const results = [
        makeUser("organizer@org.com"),
        makeUser("attendee@org.com"),
        makeUser("available@org.com"),
      ];
      const attendees = [makeAttendee("attendee@org.com")];
      const filtered = filterSuggestions(
        results,
        attendees,
        "organizer@org.com",
      );
      expect(filtered).toHaveLength(1);
      expect(filtered[0].email).toBe("available@org.com");
    });

    it("filters out users with no email", () => {
      const results = [{ id: "1", email: "", full_name: "No Email" }];
      expect(filterSuggestions(results, [])).toHaveLength(0);
    });

    it("returns empty array for empty results", () => {
      expect(filterSuggestions([], [])).toEqual([]);
    });
  });
});
