/**
 * CalDavService read-only detection.
 *
 * The client reads ``{DAV:}share-access`` to know if the user can add or
 * change events in a calendar.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

function mockResponse(status: number, body = ""): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/xml" }),
    text: async () => body,
  } as unknown as Response;
}

const calendarResponse = (uri: string, shareAccess: string) => `
  <d:response>
    <d:href>/caldav/calendars/users/me@example.com/${uri}/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>${uri}</d:displayname>
        <d:resourcetype><d:collection/><cal:calendar/></d:resourcetype>
        <d:share-access>${shareAccess}</d:share-access>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>`;

const MULTISTATUS = `<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  ${calendarResponse("own", "<d:shared-owner/>")}
  ${calendarResponse("reader", "<d:read/>")}
  ${calendarResponse("writer", "<d:read-write/>")}
</d:multistatus>`;

describe("CalDavService read-only detection", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;
  let service: CalDavService;

  beforeEach(async () => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    service = new CalDavService();
    await service.connect({ serverUrl: "http://srv/caldav/", userEmail: "me@example.com" });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("asks for share-access and marks read shares as read-only", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(207, MULTISTATUS));

    const result = await service.fetchCalendars();

    const body = String((fetchMock.mock.calls[0][1] as RequestInit).body);
    expect(body).toMatch(/<\w+:share-access\s*\/>/);
    expect(result.success).toBe(true);
    const readOnly = Object.fromEntries(
      (result.data ?? []).map((cal) => [cal.displayName, cal.readOnly]),
    );
    expect(readOnly).toEqual({ own: false, reader: true, writer: false });
  });
});
