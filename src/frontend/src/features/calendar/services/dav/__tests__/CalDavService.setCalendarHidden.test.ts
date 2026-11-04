/**
 * CalDavService hidden calendars. The client lists hidden calendars with
 * a header, reads their flag, and sets or removes it with a PROPPATCH.
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
        <d:resourcetype><d:collection/><cal:calendar/><cs:shared/></d:resourcetype>
        ${extraProps}
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>`;

const LISTING = `<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav"
  xmlns:cs="http://calendarserver.org/ns/" xmlns:ls="http://lasuite.numerique.gouv.fr/ns/">
  ${calendarResponse("shown")}
  ${calendarResponse("hidden", "<ls:calendar-hidden>true</ls:calendar-hidden>")}
</d:multistatus>`;

const proppatchResponse = (status: string) => `<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:ls="http://lasuite.numerique.gouv.fr/ns/">
  <d:response>
    <d:href>/caldav/calendars/users/me@example.com/shown/</d:href>
    <d:propstat>
      <d:prop><ls:calendar-hidden/></d:prop>
      <d:status>HTTP/1.1 ${status}</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>`;

describe("CalDavService hidden calendars", () => {
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

  it("asks for hidden calendars and reads their flag", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(207, LISTING));

    const result = await service.fetchCalendars();

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-LS-Include-Hidden"]).toBe("true");
    const flags = Object.fromEntries(
      (result.data ?? []).map((cal) => [cal.displayName, cal.hidden]),
    );
    expect(flags).toEqual({ shown: false, hidden: true });
  });

  it.each([
    [true, "200 OK", "<D:set><D:prop><LS:calendar-hidden>true</LS:calendar-hidden>"],
    [false, "204 No Content", "<D:remove><D:prop><LS:calendar-hidden/>"],
  ])("sends a PROPPATCH for hidden=%s", async (hidden, status, update) => {
    fetchMock.mockResolvedValueOnce(mockResponse(207, proppatchResponse(status)));

    const result = await service.setCalendarHidden(`${HOME}shown/`, hidden);

    expect(result.success).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${HOME}shown/`);
    expect(init.method).toBe("PROPPATCH");
    expect(init.body).toContain(update);
  });

  it("reports a refused property as a failure", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(207, proppatchResponse("403 Forbidden")));

    const result = await service.setCalendarHidden(`${HOME}shown/`, true);

    expect(result.success).toBe(false);
  });
});
