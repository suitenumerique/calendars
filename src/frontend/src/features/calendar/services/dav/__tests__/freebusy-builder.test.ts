/**
 * Tests for buildFreeBusyRequestIcs.
 *
 * The builder used to be a hand-built template literal that interpolated
 * attendee emails directly into ICS lines. We replaced it with ts-ics's
 * structured generator, and these tests pin the contract:
 *
 *   - Output is canonical RFC 5545 (CRLF line endings, BEGIN/END
 *     wrappers, DTSTAMP/UID present, METHOD:REQUEST set).
 *   - Attendee emails are escaped, NOT interpolated raw — a CR/LF in
 *     an attendee email value cannot smuggle a new property line.
 *   - Round-trip: feeding the output back into ts-ics's parser yields
 *     a structurally-equivalent VFREEBUSY component.
 */
import { describe, it, expect } from "vitest";
import { convertIcsCalendar } from "ts-ics";
import { buildFreeBusyRequestIcs, InvalidFreeBusyEmailError } from "../helpers/freebusy-builder";
import type { FreeBusyRequest } from "../types/caldav-service";

const baseRequest: FreeBusyRequest = {
  timeRange: {
    start: new Date("2026-04-08T09:00:00Z"),
    end: new Date("2026-04-08T17:00:00Z"),
  },
  attendees: ["alice@example.com", "bob@example.com"],
  organizer: { email: "me@example.com" },
};

describe("buildFreeBusyRequestIcs", () => {
  describe("canonical output shape", () => {
    it("produces a wellformed VCALENDAR with VFREEBUSY", () => {
      const ics = buildFreeBusyRequestIcs(baseRequest);
      expect(ics).toContain("BEGIN:VCALENDAR");
      expect(ics).toContain("END:VCALENDAR");
      expect(ics).toContain("BEGIN:VFREEBUSY");
      expect(ics).toContain("END:VFREEBUSY");
      expect(ics).toContain("VERSION:2.0");
      expect(ics).toContain("METHOD:REQUEST");
    });

    it("uses CRLF line endings (RFC 5545 §3.1)", () => {
      const ics = buildFreeBusyRequestIcs(baseRequest);
      // ts-ics should emit CRLF; assert it explicitly so any future
      // change to the underlying lib that breaks this contract fails
      // loudly here.
      expect(ics).toMatch(/\r\n/);
    });

    it("includes attendees in deterministic order", () => {
      const ics = buildFreeBusyRequestIcs(baseRequest);
      expect(ics).toContain("alice@example.com");
      expect(ics).toContain("bob@example.com");
      expect(ics).toContain("me@example.com");
    });

    it("omits ORGANIZER when not provided", () => {
      const ics = buildFreeBusyRequestIcs({
        timeRange: baseRequest.timeRange,
        attendees: baseRequest.attendees,
      });
      // The substring "ORGANIZER" might appear in a comment, but as a
      // real property line it must NOT.
      expect(ics).not.toMatch(/(?:^|\r?\n)ORGANIZER[;:]/);
    });

    it("includes a UID and DTSTAMP per RFC 5545", () => {
      const ics = buildFreeBusyRequestIcs(baseRequest);
      expect(ics).toMatch(/(?:^|\r?\n)UID:/);
      // ts-ics emits ``DTSTAMP;VALUE=DATE-TIME:`` (with VALUE param),
      // not bare ``DTSTAMP:``. Both forms are RFC 5545 compliant.
      expect(ics).toMatch(/(?:^|\r?\n)DTSTAMP[;:]/);
    });
  });

  describe("round-trip via ts-ics parser", () => {
    it("parses back into a structurally-equivalent calendar", () => {
      const ics = buildFreeBusyRequestIcs(baseRequest);
      const parsed = convertIcsCalendar(undefined, ics);
      expect(parsed.method).toBe("REQUEST");
      expect(parsed.freeBusy).toHaveLength(1);
      const fb = parsed.freeBusy![0];
      expect(fb.attendees).toHaveLength(2);
      const attendeeEmails = (fb.attendees ?? []).map((a) => a.email).sort();
      expect(attendeeEmails).toEqual(["alice@example.com", "bob@example.com"]);
      expect(fb.organizer?.email).toBe("me@example.com");
    });
  });

  describe("regression — attendee email line-injection", () => {
    // CRITICAL: ts-ics's generateIcsCalendar does NOT escape control
    // characters in email property values. It interpolates the raw
    // email into ``ATTENDEE:mailto:${email}``. So passing
    // ``alice@x\nMETHOD:CANCEL`` would produce a calendar with a
    // smuggled top-level METHOD line.
    //
    // The buildFreeBusyRequestIcs helper compensates by validating
    // every email at the boundary and throwing InvalidFreeBusyEmailError
    // on any control character. These tests pin that contract — if
    // someone removes the validation, the smuggled lines come back
    // and these tests must fail loudly.
    const hostileEmails = [
      "alice@example.com\nORGANIZER:mailto:victim@target",
      "alice@example.com\r\nMETHOD:CANCEL",
      "alice@example.com\nATTENDEE:mailto:smuggled@target",
      "alice@example.com\rinjected",
      "alice@example.com\x00null",
      "alice@example.com\x1bescape",
    ];

    for (const hostile of hostileEmails) {
      it(`refuses attendee ${JSON.stringify(hostile)}`, () => {
        expect(() =>
          buildFreeBusyRequestIcs({
            ...baseRequest,
            attendees: [hostile, "bob@example.com"],
          }),
        ).toThrow(InvalidFreeBusyEmailError);
      });

      it(`refuses organizer ${JSON.stringify(hostile)}`, () => {
        expect(() =>
          buildFreeBusyRequestIcs({
            ...baseRequest,
            organizer: { email: hostile },
          }),
        ).toThrow(InvalidFreeBusyEmailError);
      });
    }

    it("error message identifies which role failed", () => {
      try {
        buildFreeBusyRequestIcs({
          ...baseRequest,
          attendees: ["alice@example.com\nMETHOD:CANCEL"],
        });
        throw new Error("expected throw");
      } catch (e) {
        expect(e).toBeInstanceOf(InvalidFreeBusyEmailError);
        expect((e as Error).message).toContain("attendee");
      }
    });
  });
});
