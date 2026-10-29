/**
 * CalDavService.fetchEvent keeps the HTTP status on failure, so a 404
 * shows that the event no longer exists.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

const EVENT_URL = "http://srv/caldav/calendars/users/u@example.com/cal-uid/event-uid.ics";

describe("CalDavService.fetchEvent", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns the 404 status when the event is gone", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: new Headers(),
      text: async () => "",
    } as unknown as Response);

    const result = await new CalDavService().fetchEvent(EVENT_URL);

    expect(result.success).toBe(false);
    expect(result.status).toBe(404);
  });
});
