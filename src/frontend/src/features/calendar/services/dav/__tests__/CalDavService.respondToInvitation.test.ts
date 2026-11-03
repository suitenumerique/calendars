/**
 * CalDavService.respondToInvitation reads the event from the server,
 * refuses a response that the server copy blocks, and retries once when
 * the event changed between the read and the write.
 */
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
    updateEvent: vi.spyOn(service, "updateEvent").mockResolvedValue({ success: true }),
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
    expect(s.updateEvent).toHaveBeenCalledWith({
      eventUrl: URL,
      event: expect.objectContaining({
        uid: UID,
        attendees: [{ email: USER, partstat: "ACCEPTED" }],
      }),
      etag: "etag-1",
    });
  });

  it("responds to a scheduled occurrence with an override", async () => {
    const s = setup([master()], [SECOND]);

    const result = await s.service.respondToInvitation(URL, { ...response, occurrence: SECOND });

    expect(result.data).toEqual({ kind: "responded" });
    expect(s.createOverrideInstance).toHaveBeenCalledOnce();
    expect(s.updateEvent).not.toHaveBeenCalled();
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
    s.updateEvent.mockResolvedValueOnce({ success: false, status: 412 });

    const result = await s.service.respondToInvitation(URL, response);

    expect(result.success).toBe(true);
    expect(s.fetchEvent).toHaveBeenCalledTimes(2);
    expect(s.updateEvent).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["cancelled", { ...master(), status: "CANCELLED" }],
    ["notAttendee", { ...master(), attendees: [] }],
  ] as const)("does not write after a 412 when the event is now %s", async (blocker, changed) => {
    const s = setup([master()]);
    s.updateEvent.mockResolvedValueOnce({ success: false, status: 412 });
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
    expect(s.updateEvent).toHaveBeenCalledOnce();
  });

  it("fails after a second 412", async () => {
    const s = setup([master()]);
    s.updateEvent.mockResolvedValue({ success: false, status: 412 });

    const result = await s.service.respondToInvitation(URL, response);

    expect(result.success).toBe(false);
    expect(result.status).toBe(412);
    expect(s.updateEvent).toHaveBeenCalledTimes(2);
  });
});
