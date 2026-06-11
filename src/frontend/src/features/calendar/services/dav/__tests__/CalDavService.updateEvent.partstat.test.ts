/**
 * CalDavService.updateEvent — attendee PARTSTAT reset on reschedule.
 *
 * RFC 6638 says a reschedule (time / RRULE change) must reset attendees
 * to NEEDS-ACTION. SabreDAV only does this in the outgoing REQUEST, never
 * in the organizer's stored copy — it treats the PUT body as authoritative
 * — so the organizer client must clear the responses it persists, like
 * Apple Calendar / Thunderbird / the Google web client do. These tests pin
 * that behavior: time changes reset non-organizer attendees, title-only
 * edits preserve every response, and the organizer's own entry is never
 * reset.
 */
import type { Mock } from "vitest";
import type { IcsCalendar, IcsEvent } from "ts-ics";
import { CalDavService } from "../CalDavService";

const CAL_URL = "http://srv/cal/A/";
const EVENT_URL = `${CAL_URL}evt.ics`;

function makeEvent(overrides: Partial<IcsEvent> = {}): IcsEvent {
  return {
    uid: "evt",
    stamp: { date: new Date("2026-06-01T00:00:00Z") },
    summary: "Sprint review",
    start: { date: new Date("2026-06-13T10:00:00Z"), type: "DATE-TIME" },
    end: { date: new Date("2026-06-13T11:00:00Z"), type: "DATE-TIME" },
    organizer: { email: "org@x.test" },
    attendees: [
      { email: "org@x.test", partstat: "ACCEPTED" },
      { email: "alice@x.test", partstat: "ACCEPTED" },
    ],
    ...overrides,
  } as IcsEvent;
}

function seed(svc: CalDavService, oldEvent: IcsEvent) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (svc as any)._calendars.set(CAL_URL, { url: CAL_URL });
  const data: IcsCalendar = {
    prodId: "-//test//EN",
    version: "2.0",
    events: [oldEvent],
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (svc as any)._events.set(EVENT_URL, {
    url: EVENT_URL,
    etag: '"old"',
    calendarUrl: CAL_URL,
    data,
  });
}

function putBody(fetchMock: Mock): string {
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
  return (call?.[1]?.body as string) ?? "";
}

describe("CalDavService.updateEvent — PARTSTAT reset on reschedule", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers({ etag: '"new"' }),
      text: async () => "",
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("resets non-organizer attendees to NEEDS-ACTION when the time changes", async () => {
    const svc = new CalDavService();
    seed(svc, makeEvent());

    // Organizer moves the event two hours later. The form carries the old
    // ACCEPTED statuses forward; updateEvent must clear them.
    const moved = makeEvent({
      start: { date: new Date("2026-06-13T12:00:00Z"), type: "DATE-TIME" },
      end: { date: new Date("2026-06-13T13:00:00Z"), type: "DATE-TIME" },
    });

    const result = await svc.updateEvent({ eventUrl: EVENT_URL, event: moved, etag: '"old"' });
    expect(result.success).toBe(true);

    const body = putBody(fetchMock);
    expect(body).toContain("alice@x.test");
    expect(body).toMatch(/PARTSTAT=NEEDS-ACTION/);
    // Exactly one reset — the organizer's own entry stays ACCEPTED.
    expect(body.match(/PARTSTAT=NEEDS-ACTION/g)).toHaveLength(1);
    expect(body).toMatch(/PARTSTAT=ACCEPTED/);
  });

  it("preserves all responses on a title-only edit", async () => {
    const svc = new CalDavService();
    seed(svc, makeEvent());

    const renamed = makeEvent({ summary: "Sprint review (renamed)" });

    const result = await svc.updateEvent({ eventUrl: EVENT_URL, event: renamed, etag: '"old"' });
    expect(result.success).toBe(true);

    const body = putBody(fetchMock);
    expect(body).not.toContain("NEEDS-ACTION");
    expect(body.match(/PARTSTAT=ACCEPTED/g)).toHaveLength(2);
  });

  it("does NOT reset when the RRULE is unchanged but its keys are in a different order", async () => {
    const svc = new CalDavService();
    // Stored copy: keys in one order (as if parsed from the server).
    seed(svc, makeEvent({ recurrenceRule: { frequency: "WEEKLY", interval: 1, count: 5 } }));

    // Form copy: identical rule, keys in a different insertion order. A
    // naive JSON.stringify compare would see these as different and wrongly
    // reset every attendee; the canonical compare must treat them as equal.
    const reordered = makeEvent({
      summary: "EXT reset test (renamed)",
      recurrenceRule: { count: 5, interval: 1, frequency: "WEEKLY" },
    });

    const result = await svc.updateEvent({ eventUrl: EVENT_URL, event: reordered, etag: '"old"' });
    expect(result.success).toBe(true);

    const body = putBody(fetchMock);
    expect(body).not.toContain("NEEDS-ACTION");
    expect(body.match(/PARTSTAT=ACCEPTED/g)).toHaveLength(2);
  });

  it("treats an RRULE change as a reschedule", async () => {
    const svc = new CalDavService();
    seed(svc, makeEvent({ recurrenceRule: { frequency: "DAILY", interval: 1 } }));

    const reFreq = makeEvent({ recurrenceRule: { frequency: "WEEKLY", interval: 1 } });

    const result = await svc.updateEvent({ eventUrl: EVENT_URL, event: reFreq, etag: '"old"' });
    expect(result.success).toBe(true);

    expect(putBody(fetchMock)).toMatch(/PARTSTAT=NEEDS-ACTION/);
  });
});
