/**
 * CalDavService.truncateRecurringSeries ends a series before a date.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

const EVENT_URL = "http://srv/cal/A/evt.ics";

const ICS = [
  "BEGIN:VCALENDAR",
  "VERSION:2.0",
  "PRODID:-//test//EN",
  "BEGIN:VEVENT",
  "UID:evt",
  "DTSTAMP:20261101T000000Z",
  "DTSTART:20261201T090000Z",
  "DTEND:20261201T100000Z",
  "RRULE:FREQ=WEEKLY",
  "SEQUENCE:2",
  "SUMMARY:Weekly",
  "END:VEVENT",
  "END:VCALENDAR",
  "",
].join("\r\n");

describe("CalDavService.truncateRecurringSeries", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn(async (_url: string, init?: RequestInit) => ({
      ok: true,
      status: init?.method === "GET" ? 200 : 204,
      headers: new Headers(),
      text: async () => (init?.method === "GET" ? ICS : ""),
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("increments the SEQUENCE of the master", async () => {
    const result = await new CalDavService().truncateRecurringSeries(
      EVENT_URL,
      new Date(Date.UTC(2026, 11, 15, 9)),
      "evt",
    );

    expect(result.success).toBe(true);
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    const body = put?.[1]?.body as string;
    expect(body).toMatch(/^SEQUENCE:3$/m);
    expect(body).toMatch(/^RRULE:.*UNTIL=/m);
  });
});
