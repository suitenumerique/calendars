import { filterSuggestions, isValidEmail, parseAttendeeList } from "../attendees-utils";

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
    const makeUser = (email: string, name = "Test User"): UserSearchResult => ({
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
      const results = [makeUser("alice@org.com", "Alice"), makeUser("bob@org.com", "Bob")];
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
      expect(filtered.map((u) => u.email)).toEqual(["bob@org.com", "carol@org.com"]);
    });

    it("filters case-insensitively", () => {
      const results = [makeUser("Alice@Org.com")];
      const attendees = [makeAttendee("alice@org.com")];
      expect(filterSuggestions(results, attendees)).toHaveLength(0);
    });

    it("filters out the organizer email", () => {
      const results = [makeUser("organizer@org.com"), makeUser("other@org.com")];
      const filtered = filterSuggestions(results, [], "organizer@org.com");
      expect(filtered).toHaveLength(1);
      expect(filtered[0].email).toBe("other@org.com");
    });

    it("filters organizer case-insensitively", () => {
      const results = [makeUser("Organizer@Org.COM")];
      const filtered = filterSuggestions(results, [], "organizer@org.com");
      expect(filtered).toHaveLength(0);
    });

    it("filters both attendees and organizer together", () => {
      const results = [
        makeUser("organizer@org.com"),
        makeUser("attendee@org.com"),
        makeUser("available@org.com"),
      ];
      const attendees = [makeAttendee("attendee@org.com")];
      const filtered = filterSuggestions(results, attendees, "organizer@org.com");
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

  describe("parseAttendeeList", () => {
    const emails = (text: string) => parseAttendeeList(text).attendees.map((a) => a.email);

    it("parses a single address", () => {
      expect(parseAttendeeList(" user@example.com ")).toEqual({
        attendees: [{ email: "user@example.com" }],
        invalid: [],
      });
    });

    it("returns nothing for an empty string", () => {
      expect(parseAttendeeList("  ")).toEqual({ attendees: [], invalid: [] });
    });

    it("splits on comma, semicolon, newline, tab and space", () => {
      expect(emails("a@x.org, b@x.org; c@x.org\nd@x.org\r\ne@x.org\tf@x.org g@x.org")).toEqual([
        "a@x.org",
        "b@x.org",
        "c@x.org",
        "d@x.org",
        "e@x.org",
        "f@x.org",
        "g@x.org",
      ]);
    });

    it("ignores empty entries", () => {
      expect(parseAttendeeList("a@x.org,, ;\n b@x.org,")).toEqual({
        attendees: [{ email: "a@x.org" }, { email: "b@x.org" }],
        invalid: [],
      });
    });

    it("normalizes to lowercase", () => {
      expect(emails("Alice@Org.COM")).toEqual(["alice@org.com"]);
    });

    it("removes duplicates case-insensitively", () => {
      expect(emails("a@x.org, A@X.org; a@x.org")).toEqual(["a@x.org"]);
    });

    it("reads the name and the address of a named entry", () => {
      expect(parseAttendeeList("Jane Doe <Jane@x.org>, <b@x.org>").attendees).toEqual([
        { email: "jane@x.org", cn: "Jane Doe" },
        { email: "b@x.org" },
      ]);
    });

    it("keeps a separator inside a quoted name", () => {
      expect(parseAttendeeList('"Doe, Jane" <jane@x.org>; b@x.org').attendees).toEqual([
        { email: "jane@x.org", cn: "Doe, Jane" },
        { email: "b@x.org" },
      ]);
    });

    it("keeps an address with a quoted local part", () => {
      expect(parseAttendeeList('"john"@x.org, b@x.org').attendees).toEqual([
        { email: '"john"@x.org' },
        { email: "b@x.org" },
      ]);
    });

    it("reads a quoted address as the name of a named entry", () => {
      expect(
        parseAttendeeList(
          `"jane@x.org" <jane@x.org>; 'bob@x.org' <bob@x.org>; "Al al@old.org" <al@x.org>`,
        ),
      ).toEqual({
        attendees: [
          { email: "jane@x.org", cn: "jane@x.org" },
          { email: "bob@x.org", cn: "bob@x.org" },
          { email: "al@x.org", cn: "Al al@old.org" },
        ],
        invalid: [],
      });
    });

    it("separates plain addresses from named entries without a separator", () => {
      expect(
        parseAttendeeList("o'neil@x.org Jane Doe <jane@x.org> Bob <bob@x.org> c@x.org oops"),
      ).toEqual({
        attendees: [
          { email: "o'neil@x.org" },
          { email: "jane@x.org", cn: "Jane Doe" },
          { email: "bob@x.org", cn: "Bob" },
          { email: "c@x.org" },
        ],
        invalid: ["oops"],
      });
    });

    it("returns the invalid tokens as written", () => {
      expect(parseAttendeeList("a@x.org, Not-An-Email; Jane <jane@>\nb@x.org")).toEqual({
        attendees: [{ email: "a@x.org" }, { email: "b@x.org" }],
        invalid: ["Not-An-Email", "Jane <jane@>"],
      });
    });

    it("keeps an entry with an unclosed quote", () => {
      expect(parseAttendeeList('"abc, a@x.org')).toEqual({
        attendees: [{ email: "a@x.org" }],
        invalid: ['"abc'],
      });
    });
  });
});
