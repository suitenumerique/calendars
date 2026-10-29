/**
 * CalDavService.fetchOccurrenceDates reads the occurrences that the
 * server expands for one event.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

const CALENDAR_URL = "http://srv/caldav/calendars/users/u@example.com/cal-uid/";
const EVENT_URL = `${CALENDAR_URL}event-uid.ics`;

const instance = (uid: string, recurrenceId: string) =>
  [
    "BEGIN:VEVENT",
    `UID:${uid}`,
    "DTSTAMP:20261101T000000Z",
    `DTSTART:${recurrenceId}`,
    `RECURRENCE-ID:${recurrenceId}`,
    "SUMMARY:Weekly",
    "END:VEVENT",
  ].join("\r\n");

const response = (href: string, ...vevents: string[]) => `
  <d:response>
    <d:href>${href}</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>"1"</d:getetag>
        <cal:calendar-data>${[
          "BEGIN:VCALENDAR",
          "VERSION:2.0",
          "PRODID:-//Test//EN",
          ...vevents,
          "END:VCALENDAR",
        ].join("\r\n")}</cal:calendar-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>`;

describe("CalDavService.fetchOccurrenceDates", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns the RECURRENCE-IDs of the event from an expand REPORT", async () => {
    const body = `<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  ${response(
    "/caldav/calendars/users/u@example.com/cal-uid/event-uid.ics",
    instance("event-uid", "20261103T080000Z"),
    instance("event-uid", "20261104T080000Z"),
  )}
  ${response(
    "/caldav/calendars/users/u@example.com/cal-uid/other.ics",
    instance("other", "20261103T100000Z"),
  )}
</d:multistatus>`;
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 207,
      headers: new Headers({ "content-type": "application/xml" }),
      text: async () => body,
    } as unknown as Response);

    const result = await new CalDavService().fetchOccurrenceDates(EVENT_URL, "event-uid", {
      start: new Date("2026-11-02T09:00:00Z"),
      end: new Date("2026-11-04T09:00:00Z"),
    });

    expect(result.data).toEqual([
      new Date("2026-11-03T08:00:00Z"),
      new Date("2026-11-04T08:00:00Z"),
    ]);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(CALENDAR_URL);
    expect(init.method).toBe("REPORT");
    expect(init.body).toContain('<C:expand start="20261102T090000Z" end="20261104T090000Z"/>');
    expect(init.body).toContain(
      '<C:prop-filter name="UID"><C:text-match collation="i;octet">event-uid</C:text-match>',
    );
  });
});
