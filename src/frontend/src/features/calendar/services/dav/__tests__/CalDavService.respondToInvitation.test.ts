/**
 * CalDavService.respondToInvitation reads the event from the server,
 * refuses a response that the server copy blocks, and retries once when
 * the event changed between the read and the write.
 */
import type { Mock } from "vitest";
import type { IcsEvent } from "ts-ics";

import { CalDavService } from "../CalDavService";

const URL = "http://srv/caldav/calendars/users/u@example.com/cal/event.ics";
const UID = "event-uid";
const USER = "bob@example.com";
const START = new Date("2026-11-02T09:00:00Z");
const SECOND = new Date("2026-11-03T09:00:00Z");

const master = (): IcsEvent =>
  ({
    uid: UID,
    stamp: { date: START },
    start: { date: START, type: "DATE-TIME" },
    summary: "Daily",
    recurrenceRule: { frequency: "DAILY", count: 3 },
    attendees: [{ email: USER, partstat: "NEEDS-ACTION" }],
  }) as IcsEvent;

const override = (): IcsEvent =>
  ({
    ...master(),
    start: { date: SECOND, type: "DATE-TIME" },
    recurrenceRule: undefined,
    recurrenceId: { value: { date: SECOND, type: "DATE-TIME" } },
  }) as IcsEvent;

const http = (status: number) =>
  ({
    ok: status < 300,
    status,
    headers: new Headers(),
    text: async () => "",
  }) as unknown as Response;

const originalFetch = globalThis.fetch;
let put: Mock;

beforeEach(() => {
  put = vi.fn().mockResolvedValue(http(204));
  globalThis.fetch = put as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

const setup = (events: IcsEvent[], occurrenceDates: Date[] = []) => {
  const service = new CalDavService();
  const spies = {
    fetchEvent: vi.spyOn(service, "fetchEvent").mockResolvedValue({
      success: true,
      data: { data: { events }, etag: "etag-1" },
    } as never),
    fetchOccurrenceDates: vi
      .spyOn(service, "fetchOccurrenceDates")
      .mockResolvedValue({ success: true, data: occurrenceDates }),
    createOverrideInstance: vi
      .spyOn(service, "createOverrideInstance")
      .mockResolvedValue({ success: true }),
  };
  return { service, ...spies };
};

const response = { uid: UID, attendeeEmail: USER, partstat: "ACCEPTED" as const };

describe("CalDavService.respondToInvitation", () => {
  it("responds to the series on the master, with the ETag of the read", async () => {
    const s = setup([master()]);

    const result = await s.service.respondToInvitation(URL, response);

    expect(result).toEqual({ success: true, data: { kind: "responded" } });
    const [url, init] = put.mock.calls[0];
    expect(url).toBe(URL);
    expect(init.method).toBe("PUT");
    expect(init.headers["If-Match"]).toBe("etag-1");
    expect(init.body).toContain("PARTSTAT=ACCEPTED");
  });

  it("answers all occurrences on the master and on the overrides", async () => {
    const THIRD = new Date("2026-11-04T09:00:00Z");
    const cancelled = {
      ...override(),
      status: "CANCELLED",
      recurrenceId: { value: { date: THIRD, type: "DATE-TIME" } },
    } as IcsEvent;
    const s = setup([master(), override(), cancelled]);

    await s.service.respondToInvitation(URL, response);

    const body: string = put.mock.calls[0][1].body;
    expect(body.match(/PARTSTAT=ACCEPTED/g)).toHaveLength(2);
    expect(body.match(/PARTSTAT=NEEDS-ACTION/g)).toHaveLength(1);
  });

  it("keeps the overrides of the read when it responds to the series", async () => {
    const s = setup([master(), override()]);

    await s.service.respondToInvitation(URL, response);

    expect(put.mock.calls[0][1].body).toMatch(/^RECURRENCE-ID/m);
  });

  it("responds to a scheduled occurrence with a new override", async () => {
    const s = setup([master()], [SECOND]);

    const result = await s.service.respondToInvitation(URL, { ...response, occurrence: SECOND });

    expect(result.data).toEqual({ kind: "responded" });
    expect(s.createOverrideInstance).toHaveBeenCalledOnce();
    expect(put).not.toHaveBeenCalled();
  });

  it("builds the response from the existing override", async () => {
    const s = setup([master(), { ...override(), summary: "Moved by the organizer" }]);

    await s.service.respondToInvitation(URL, { ...response, occurrence: SECOND });

    expect(s.createOverrideInstance).toHaveBeenCalledWith(
      URL,
      expect.objectContaining({
        summary: "Moved by the organizer",
        attendees: [{ email: USER, partstat: "ACCEPTED" }],
      }),
      SECOND,
      "etag-1",
    );
  });

  it.each([
    ["the occurrence", { occurrence: SECOND }],
    ["all occurrences", {}],
  ])("answers %s in place when the copy has no master", async (_, choice) => {
    const s = setup([override()]);

    const result = await s.service.respondToInvitation(URL, { ...response, ...choice });

    expect(result.data).toEqual({ kind: "responded" });
    expect(s.createOverrideInstance).not.toHaveBeenCalled();
    expect(put.mock.calls[0][1].body).toMatch(/^RECURRENCE-ID/m);
    expect(put.mock.calls[0][1].body).toContain("PARTSTAT=ACCEPTED");
  });

  it("answers all occurrences of a copy without master", async () => {
    const third = new Date("2026-11-04T09:00:00Z");
    const other = {
      ...override(),
      start: { date: third, type: "DATE-TIME" },
      recurrenceId: { value: { date: third, type: "DATE-TIME" } },
    } as IcsEvent;
    const s = setup([override(), other]);

    const result = await s.service.respondToInvitation(URL, response);

    expect(result.data).toEqual({ kind: "responded" });
    const body: string = put.mock.calls[0][1].body;
    expect(body.match(/PARTSTAT=ACCEPTED/g)).toHaveLength(2);
    expect(body).not.toContain("NEEDS-ACTION");
  });

  it("does not write an occurrence of a series in an unknown timezone", async () => {
    const tzid = "W. Europe Standard Time";
    const start = {
      date: START,
      type: "DATE-TIME",
      local: { date: START, timezone: tzid, tzoffset: "+0100" },
    };
    const s = setup([{ ...master(), start } as IcsEvent], [SECOND]);

    const result = await s.service.respondToInvitation(URL, { ...response, occurrence: SECOND });

    expect(result.success).toBe(false);
    expect(s.createOverrideInstance).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
  });

  it("responds to the event when the master has no RRULE", async () => {
    const s = setup([{ ...master(), recurrenceRule: undefined }], [START]);

    const result = await s.service.respondToInvitation(URL, { ...response, occurrence: START });

    expect(result.data).toEqual({ kind: "responded" });
    expect(s.createOverrideInstance).not.toHaveBeenCalled();
    expect(put.mock.calls[0][1].body).toContain("PARTSTAT=ACCEPTED");
    expect(put.mock.calls[0][1].body).not.toMatch(/^(EXDATE|RECURRENCE-ID)/m);
  });

  it("refuses an occurrence that the expansion does not contain", async () => {
    const s = setup([master()], []);

    const result = await s.service.respondToInvitation(URL, { ...response, occurrence: SECOND });

    expect(result).toEqual({ success: true, data: { kind: "blocked", blocker: "cancelled" } });
    expect(s.createOverrideInstance).not.toHaveBeenCalled();
  });

  it("refuses a deleted event", async () => {
    const s = setup([]);
    s.fetchEvent.mockResolvedValueOnce({ success: false, status: 404 });

    const result = await s.service.respondToInvitation(URL, response);

    expect(result.data).toEqual({ kind: "blocked", blocker: "deleted" });
  });

  it("reads the event again and retries once on a 412", async () => {
    const s = setup([master()]);
    s.fetchEvent.mockResolvedValueOnce({
      success: true,
      data: { data: { events: [master()] }, etag: "etag-1" },
    } as never);
    s.fetchEvent.mockResolvedValueOnce({
      success: true,
      data: { data: { events: [{ ...master(), summary: "Organizer edit" }] }, etag: "etag-2" },
    } as never);
    put.mockResolvedValueOnce(http(412));

    const result = await s.service.respondToInvitation(URL, response);

    expect(result.success).toBe(true);
    expect(put).toHaveBeenCalledTimes(2);
    expect(put.mock.calls[1][1].headers["If-Match"]).toBe("etag-2");
    expect(put.mock.calls[1][1].body).toContain("SUMMARY:Organizer edit");
  });

  it.each([
    ["cancelled", { ...master(), status: "CANCELLED" }],
    ["notAttendee", { ...master(), attendees: [] }],
  ] as const)("does not write after a 412 when the event is now %s", async (blocker, changed) => {
    const s = setup([master()]);
    put.mockResolvedValueOnce(http(412));
    s.fetchEvent.mockResolvedValueOnce({
      success: true,
      data: { data: { events: [master()] }, etag: "etag-1" },
    } as never);
    s.fetchEvent.mockResolvedValueOnce({
      success: true,
      data: { data: { events: [changed as IcsEvent] }, etag: "etag-2" },
    } as never);

    const result = await s.service.respondToInvitation(URL, response);

    expect(result).toEqual({ success: true, data: { kind: "blocked", blocker } });
    expect(put).toHaveBeenCalledOnce();
  });

  it("fails after a second 412", async () => {
    const s = setup([master()]);
    put.mockResolvedValue(http(412));

    const result = await s.service.respondToInvitation(URL, response);

    expect(result.success).toBe(false);
    expect(result.status).toBe(412);
    expect(put).toHaveBeenCalledTimes(2);
  });
});
