/**
 * CalDavService.updateEvent, organizer of a series.
 *
 * SabreDAV refuses a series whose components have different organizers.
 * A move of a series without guests does not change the organizer on the
 * server, so the update that follows must change it in all the components.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

const SOURCE_URL = "http://srv/cal/A/evt.ics";
const TARGET_CAL_URL = "http://srv/cal/B/";

/** A series with one edited occurrence, as the server stores it. */
const series = (overrideOrganizer?: string): string =>
  [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//test//EN",
    "BEGIN:VEVENT",
    "UID:evt",
    "DTSTAMP:20260601T000000Z",
    "DTSTART:20260613T100000Z",
    "DTEND:20260613T110000Z",
    "RRULE:FREQ=DAILY;COUNT=5",
    "SUMMARY:Series",
    "ORGANIZER:mailto:team@x.test",
    "END:VEVENT",
    "BEGIN:VEVENT",
    "UID:evt",
    "DTSTAMP:20260601T000000Z",
    "RECURRENCE-ID:20260614T100000Z",
    "DTSTART:20260614T120000Z",
    "DTEND:20260614T130000Z",
    "SUMMARY:Series (edited)",
    ...(overrideOrganizer ? [`ORGANIZER:mailto:${overrideOrganizer}`] : []),
    "END:VEVENT",
    "END:VCALENDAR",
    "",
  ].join("\r\n");

describe("CalDavService.updateEvent, organizer of a series", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  /** Move the series, read it, then update its master with a new organizer. */
  const moveThenUpdate = async (stored: string): Promise<string> => {
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => ({
      ok: true,
      status: init?.method === "GET" ? 200 : init?.method === "MOVE" ? 201 : 204,
      headers: new Headers({ etag: '"etag"' }),
      text: async () => (init?.method === "GET" ? stored : ""),
    }));

    const svc = new CalDavService();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (svc as any)._calendars.set(TARGET_CAL_URL, { url: TARGET_CAL_URL });

    const move = await svc.moveEvent({
      sourceEventUrl: SOURCE_URL,
      targetCalendarUrl: TARGET_CAL_URL,
    });
    const moved = await svc.fetchEvent(move.data!.url);
    const master = moved.data!.data.events!.find((e) => !e.recurrenceId)!;
    const result = await svc.updateEvent({
      eventUrl: move.data!.url,
      event: { ...master, organizer: { email: "me@x.test" } },
      etag: moved.data!.etag,
    });
    expect(result.success).toBe(true);

    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    return (put?.[1]?.body as string) ?? "";
  };

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("gives the new organizer of the series to its overrides", async () => {
    const body = await moveThenUpdate(series("team@x.test"));

    expect(body.match(/ORGANIZER[^\r\n]*me@x\.test/g)).toHaveLength(2);
    expect(body).not.toContain("team@x.test");
  });

  it("does not add an organizer to an override that has none", async () => {
    const body = await moveThenUpdate(series());

    expect(body.match(/ORGANIZER/g)).toHaveLength(1);
  });
});
