/**
 * CalDavService.deleteEvent — idempotent + ETag-retry behaviour.
 *
 * The delete flow needs to absorb two real-world races without surfacing
 * a confusing precondition error to the user:
 *
 *   (a) the cached ETag drifted (the most common path — drag-drop, RSVP,
 *       another device wrote between the modal opening and clicking
 *       delete). The server returns 412 with the *current* ETag in the
 *       headers; we refetch and retry once with that fresh ETag.
 *   (b) the event was already deleted elsewhere. SabreDAV still answers
 *       412 in this case ("If-Match was specified and the resource did
 *       not exist") because no ETag can match a missing resource. The
 *       refetch then 404s, which we treat as success — the caller's
 *       intent ("event is gone") is already fulfilled.
 *
 * A bare 404 on the initial DELETE is also treated as success for the
 * same reason: delete is idempotent.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

const EVENT_URL = "http://srv/caldav/calendars/users/u@example.com/cal-uid/event-uid.ics";

function mockResponse(init: { status: number; etag?: string; body?: string }): Response {
  const headers = new Headers();
  if (init.etag) headers.set("etag", init.etag);
  return {
    ok: init.status >= 200 && init.status < 300,
    status: init.status,
    headers,
    text: async () => init.body ?? "",
  } as unknown as Response;
}

describe("CalDavService.deleteEvent", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("DELETE 204 → success on first try", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse({ status: 204 }));

    const result = await new CalDavService().deleteEvent(EVENT_URL, '"e1"');

    expect(result.success).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("DELETE");
    expect(init.headers["If-Match"]).toBe('"e1"');
  });

  it("DELETE 404 → idempotent success (event already gone)", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse({ status: 404 }));

    const result = await new CalDavService().deleteEvent(EVENT_URL, '"e1"');

    expect(result.success).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("DELETE 412 + GET 200 + retry DELETE 204 → success with fresh ETag", async () => {
    fetchMock
      .mockResolvedValueOnce(mockResponse({ status: 412 })) // stale ETag
      .mockResolvedValueOnce(
        mockResponse({
          status: 200,
          etag: '"fresh-etag"',
          body: "BEGIN:VCALENDAR\r\nEND:VCALENDAR",
        }),
      )
      .mockResolvedValueOnce(mockResponse({ status: 204 }));

    const result = await new CalDavService().deleteEvent(EVENT_URL, '"stale"');

    expect(result.success).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    expect(fetchMock.mock.calls[1][1].method).toBe("GET");
    expect(fetchMock.mock.calls[2][1].method).toBe("DELETE");
    expect(fetchMock.mock.calls[2][1].headers["If-Match"]).toBe('"fresh-etag"');
  });

  it("DELETE 412 + GET 404 → success (resource was already deleted)", async () => {
    // SabreDAV reports a missing-resource If-Match as 412, not 404.
    // The refetch is what disambiguates: if the resource is gone, the
    // delete intent is fulfilled.
    fetchMock
      .mockResolvedValueOnce(mockResponse({ status: 412 }))
      .mockResolvedValueOnce(mockResponse({ status: 404 }));

    const result = await new CalDavService().deleteEvent(EVENT_URL, '"stale"');

    expect(result.success).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    expect(fetchMock.mock.calls[1][1].method).toBe("GET");
  });

  it("DELETE 412 + GET 200 + retry DELETE 404 → success (raced with another deleter)", async () => {
    fetchMock
      .mockResolvedValueOnce(mockResponse({ status: 412 }))
      .mockResolvedValueOnce(
        mockResponse({
          status: 200,
          etag: '"fresh-etag"',
          body: "BEGIN:VCALENDAR\r\nEND:VCALENDAR",
        }),
      )
      .mockResolvedValueOnce(mockResponse({ status: 404 }));

    const result = await new CalDavService().deleteEvent(EVENT_URL, '"stale"');

    expect(result.success).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("DELETE 412 + GET 200 + retry DELETE 412 → propagates as failure", async () => {
    // A second 412 means the ETag is still wrong even after refetching —
    // either a real conflict the user needs to know about, or a server
    // bug. Either way, surface it.
    fetchMock
      .mockResolvedValueOnce(mockResponse({ status: 412 }))
      .mockResolvedValueOnce(
        mockResponse({
          status: 200,
          etag: '"fresh-etag"',
          body: "BEGIN:VCALENDAR\r\nEND:VCALENDAR",
        }),
      )
      .mockResolvedValueOnce(mockResponse({ status: 412 }));

    const result = await new CalDavService().deleteEvent(EVENT_URL, '"stale"');

    expect(result.success).toBe(false);
    expect(result.status).toBe(412);
  });

  it("DELETE 500 → propagates as failure (no retry)", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse({ status: 500 }));

    const result = await new CalDavService().deleteEvent(EVENT_URL, '"e1"');

    expect(result.success).toBe(false);
    expect(result.status).toBe(500);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
