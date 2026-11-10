/**
 * CalDavService.createOverrideInstance adds or replaces the override of
 * an occurrence.
 */
import type { Mock } from "vitest";
import { convertIcsCalendar } from "ts-ics";
import { CalDavService } from "../CalDavService";

const EVENT_URL = "http://srv/caldav/calendars/users/u@example.com/cal-uid/event-uid.ics";

// A weekly series at 09:00 in Paris. The override of 2026-11-03 has a UTC
// RECURRENCE-ID: 09:00 in Paris is 08:00Z in winter.
const ICS = [
  "BEGIN:VCALENDAR",
  "VERSION:2.0",
  "PRODID:-//test//EN",
  "BEGIN:VEVENT",
  "UID:series-uid",
  "DTSTAMP:20261001T000000Z",
  "DTSTART;TZID=Europe/Paris:20261027T090000",
  "DTEND;TZID=Europe/Paris:20261027T100000",
  "RRULE:FREQ=WEEKLY",
  "SUMMARY:Weekly",
  "END:VEVENT",
  "BEGIN:VEVENT",
  "UID:series-uid",
  "DTSTAMP:20261001T000000Z",
  "RECURRENCE-ID:20261103T080000Z",
  "DTSTART:20261103T080000Z",
  "DTEND:20261103T090000Z",
  "SUMMARY:Weekly",
  "ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:a@example.com",
  "END:VEVENT",
  "END:VCALENDAR",
].join("\r\n");

const response = (status: number, body = ""): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    text: async () => body,
  }) as unknown as Response;

describe("CalDavService.createOverrideInstance", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: Mock;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("replaces an override with a UTC RECURRENCE-ID", async () => {
    fetchMock.mockResolvedValueOnce(response(200, ICS)).mockResolvedValueOnce(response(204));
    const override = convertIcsCalendar(undefined, ICS).events!.find((e) => e.recurrenceId)!;
    const reply = {
      ...override,
      attendees: override.attendees?.map((a) => ({ ...a, partstat: "ACCEPTED" as const })),
    };

    const result = await new CalDavService().createOverrideInstance(
      EVENT_URL,
      reply,
      new Date(Date.UTC(2026, 10, 3, 9, 0, 0)),
      "etag-1",
    );

    expect(result.success).toBe(true);
    const put = fetchMock.mock.calls[1][1] as RequestInit;
    const body = put.body as string;
    expect(body.match(/^RECURRENCE-ID/gm)).toHaveLength(1);
    expect(body).not.toMatch(/^EXDATE/m);
    expect(body).toContain("PARTSTAT=ACCEPTED");
    expect((put.headers as Record<string, string>)["If-Match"]).toBe("etag-1");
  });

  it("keeps the override of another occurrence at the same UTC digits", async () => {
    // An hourly series. In winter, 09:00Z is 10:00 in Paris: another
    // occurrence than 09:00 in Paris, which the call targets.
    const hourly = ICS.replace("RRULE:FREQ=WEEKLY", "RRULE:FREQ=HOURLY")
      .replace("RECURRENCE-ID:20261103T080000Z", "RECURRENCE-ID:20261103T090000Z")
      .replace("DTSTART:20261103T080000Z", "DTSTART:20261103T090000Z")
      .replace("DTEND:20261103T090000Z", "DTEND:20261103T100000Z");
    fetchMock.mockResolvedValueOnce(response(200, hourly)).mockResolvedValueOnce(response(204));
    const master = convertIcsCalendar(undefined, hourly).events!.find((e) => !e.recurrenceId)!;

    const result = await new CalDavService().createOverrideInstance(
      EVENT_URL,
      master,
      new Date(Date.UTC(2026, 10, 3, 9, 0, 0)),
    );

    expect(result.success).toBe(true);
    const body = (fetchMock.mock.calls[1][1] as RequestInit).body as string;
    expect(body.match(/^RECURRENCE-ID/gm)).toHaveLength(2);
    expect(body).toMatch(/^RECURRENCE-ID[^:\r\n]*:20261103T090000Z\r?$/m);
    expect(body).toMatch(/^RECURRENCE-ID[^:\r\n]*TZID=Europe\/Paris:20261103T090000\r?$/m);
  });

  it("adds an override without an EXDATE on the master", async () => {
    fetchMock.mockResolvedValueOnce(response(200, ICS)).mockResolvedValueOnce(response(204));
    const master = convertIcsCalendar(undefined, ICS).events!.find((e) => !e.recurrenceId)!;

    const result = await new CalDavService().createOverrideInstance(
      EVENT_URL,
      master,
      new Date(Date.UTC(2026, 10, 10, 9, 0, 0)),
    );

    expect(result.success).toBe(true);
    const body = (fetchMock.mock.calls[1][1] as RequestInit).body as string;
    expect(body).not.toMatch(/^EXDATE/m);
    expect(body.match(/^RECURRENCE-ID/gm)).toHaveLength(2);
    expect(body).toMatch(/^RECURRENCE-ID[^:\r\n]*TZID=Europe\/Paris:20261110T090000\r?$/m);
  });

  it("keeps an EXDATE that an older version added", async () => {
    // Older versions added an EXDATE with each override. The call must
    // replace the override and keep the EXDATE.
    const withExdate = ICS.replace(
      "RRULE:FREQ=WEEKLY",
      "RRULE:FREQ=WEEKLY\r\nEXDATE:20261103T080000Z",
    );
    fetchMock.mockResolvedValueOnce(response(200, withExdate)).mockResolvedValueOnce(response(204));
    const override = convertIcsCalendar(undefined, withExdate).events!.find((e) => e.recurrenceId)!;

    const result = await new CalDavService().createOverrideInstance(
      EVENT_URL,
      override,
      new Date(Date.UTC(2026, 10, 3, 9, 0, 0)),
    );

    expect(result.success).toBe(true);
    const body = (fetchMock.mock.calls[1][1] as RequestInit).body as string;
    expect(body.match(/^EXDATE/gm)).toHaveLength(1);
    expect(body.match(/^RECURRENCE-ID/gm)).toHaveLength(1);
  });
});
