/**
 * CalDavService.moveEvent — request-shape regression test.
 *
 * MOVE is built via raw fetch (tsdav doesn't expose a high-level move).
 * The unified `davRequest` carries session-cookie auth via
 * `credentials: 'include'` and the shared `X-LS-Client: web` header, so
 * moveEvent no longer needs to splice per-calendar `Authorization`
 * headers — those used to be the source of an opaque 401 when the
 * source calendar entry wasn't cached. This test pins the request
 * shape so a future refactor can't silently regress it.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

type CalendarStubInit = {
  url: string;
};

function injectCalendar(svc: CalDavService, init: CalendarStubInit) {
  // _calendars is private; we poke it directly because constructing a
  // real one through connect() would require mocking the entire tsdav
  // PROPFIND chain.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const calendars: Map<string, unknown> = (svc as any)._calendars;
  calendars.set(init.url, {
    url: init.url,
    // The remaining fields are unused by moveEvent but required by
    // CalDavCalendar — leave as undefined.
  });
}

describe("CalDavService.moveEvent — request shape", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      headers: new Headers({ etag: '"new-etag"' }),
      text: async () => "",
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("issues MOVE with correct Destination/If-Match and includes credentials", async () => {
    const svc = new CalDavService();
    const targetCalendarUrl = "http://srv/cal/B/";
    const sourceEventUrl = "http://srv/cal/A/event-uid.ics";

    // Even when the source calendar isn't cached, the request must go
    // out cleanly — auth is provided by `credentials: 'include'`, not
    // by per-calendar header splicing.
    injectCalendar(svc, { url: targetCalendarUrl });

    const result = await svc.moveEvent({
      sourceEventUrl,
      targetCalendarUrl,
      sourceEtag: '"src-etag"',
    });

    expect(result.success).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [calledUrl, init] = fetchMock.mock.calls[0];
    expect(calledUrl).toBe(sourceEventUrl);
    expect(init.method).toBe("MOVE");
    expect(init.headers).toMatchObject({
      Destination: "http://srv/cal/B/event-uid.ics",
      Overwrite: "F",
      "If-Match": '"src-etag"',
      "X-LS-Client": "web",
    });
    expect(init.credentials).toBe("include");
  });

  it("omits If-Match when no sourceEtag is provided", async () => {
    const svc = new CalDavService();
    const sourceCalendarUrl = "http://srv/cal/A/";
    const targetCalendarUrl = "http://srv/cal/B/";
    const sourceEventUrl = `${sourceCalendarUrl}event-uid.ics`;

    injectCalendar(svc, { url: targetCalendarUrl });
    injectCalendar(svc, { url: sourceCalendarUrl });

    const result = await svc.moveEvent({
      sourceEventUrl,
      targetCalendarUrl,
    });

    expect(result.success).toBe(true);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["If-Match"]).toBeUndefined();
  });
});
