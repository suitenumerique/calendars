/**
 * CalDavService calendar deletion. The client reads the sync-managed
 * flag from the PROPFIND, and reports a refused DELETE as a failure.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

const HOME = "http://srv/caldav/calendars/users/me@example.com/";

function mockResponse(status: number, body = "", contentType = "application/xml"): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": contentType }),
    text: async () => body,
  } as unknown as Response;
}

const calendarResponse = (uri: string, extraProps = "") => `
  <d:response>
    <d:href>/caldav/calendars/users/me@example.com/${uri}/</d:href>
    <d:propstat>
      <d:prop>
        <d:displayname>${uri}</d:displayname>
        <d:resourcetype><d:collection/><cal:calendar/></d:resourcetype>
        ${extraProps}
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>`;

const MAILBOX = "<ls:calendar-owner-type>MAILBOX</ls:calendar-owner-type>";

const MULTISTATUS = `<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav"
  xmlns:ls="http://lasuite.numerique.gouv.fr/ns/">
  ${calendarResponse("private")}
  ${calendarResponse(
    "team-synced",
    `${MAILBOX}<ls:calendar-sync-managed>true</ls:calendar-sync-managed>`,
  )}
  ${calendarResponse("team-manual", MAILBOX)}
</d:multistatus>`;

describe("CalDavService calendar deletion", () => {
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

  it("reads the sync-managed flag of each calendar from the PROPFIND", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(207, MULTISTATUS));

    const result = await service.fetchCalendars();

    expect(result.success).toBe(true);
    const flags = Object.fromEntries(
      (result.data ?? []).map((cal) => [cal.displayName, cal.syncManaged]),
    );
    expect(flags).toEqual({
      private: false,
      "team-synced": true,
      "team-manual": false,
    });
  });

  it("sends a DELETE to the calendar URL", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(204));

    const result = await service.deleteCalendar(`${HOME}private/`);

    expect(result.success).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${HOME}private/`);
    expect(init.method).toBe("DELETE");
  });

  it("reports a refused DELETE as a failure with its status", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        403,
        '<?xml version="1.0"?><d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">' +
          "<s:message>This calendar is managed by Messages.</s:message></d:error>",
      ),
    );

    const result = await service.deleteCalendar(`${HOME}team-synced/`);

    expect(result).toEqual({
      success: false,
      status: 403,
      error: "This calendar is managed by Messages.",
    });
  });
});
