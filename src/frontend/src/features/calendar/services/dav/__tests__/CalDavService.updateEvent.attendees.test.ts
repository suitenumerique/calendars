/**
 * CalDavService.updateEvent, attendees of a series.
 *
 * An attendee change of the master also applies to the overrides. Then
 * SabreDAV cancels the whole event for a removed attendee, and invites a
 * new attendee to all the dates.
 */
import type { Mock } from "vitest";
import { CalDavService } from "../CalDavService";

const EVENT_URL = "http://srv/cal/A/evt.ics";
const CAL_URL = "http://srv/cal/A/";

const ICS = [
  "BEGIN:VCALENDAR",
  "VERSION:2.0",
  "PRODID:-//test//EN",
  "BEGIN:VEVENT",
  "UID:evt",
  "DTSTAMP:20261101T000000Z",
  "DTSTART:20261201T090000Z",
  "DTEND:20261201T100000Z",
  "RRULE:FREQ=WEEKLY;COUNT=4",
  "SUMMARY:Weekly",
  "ORGANIZER:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=ACCEPTED:mailto:a@x.test",
  "ATTENDEE;PARTSTAT=ACCEPTED:mailto:b@x.test",
  "END:VEVENT",
  "BEGIN:VEVENT",
  "UID:evt",
  "DTSTAMP:20261101T000000Z",
  "RECURRENCE-ID:20261215T090000Z",
  "DTSTART:20261215T140000Z",
  "DTEND:20261215T150000Z",
  "SUMMARY:Weekly",
  "ORGANIZER:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=ACCEPTED:mailto:a@x.test",
  "ATTENDEE;PARTSTAT=DECLINED:mailto:b@x.test",
  "END:VEVENT",
  "END:VCALENDAR",
  "",
].join("\r\n");

describe("CalDavService.updateEvent, attendees of a series", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn(async (_url: string, init?: RequestInit) => ({
      ok: true,
      status: init?.method === "GET" ? 200 : 204,
      headers: new Headers({ etag: '"etag"' }),
      text: async () => (init?.method === "GET" ? ICS : ""),
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("applies the attendee change of the master to the overrides", async () => {
    const svc = new CalDavService();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (svc as any)._calendars.set(CAL_URL, { url: CAL_URL });
    const fetched = await svc.fetchEvent(EVENT_URL);
    const master = fetched.data!.data.events!.find((e) => !e.recurrenceId)!;

    const result = await svc.updateEvent({
      eventUrl: EVENT_URL,
      event: {
        ...master,
        attendees: [
          master.attendees![1],
          { email: "c@x.test", partstat: "NEEDS-ACTION", rsvp: true },
        ],
      },
      etag: fetched.data!.etag,
    });
    expect(result.success).toBe(true);

    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    const body = put?.[1]?.body as string;
    expect(body).not.toContain("a@x.test");
    expect(body.match(/ATTENDEE[^\r\n]*c@x\.test/g)).toHaveLength(2);
    expect(body).toMatch(/PARTSTAT=DECLINED[^\r\n]*b@x\.test/);
  });
});
