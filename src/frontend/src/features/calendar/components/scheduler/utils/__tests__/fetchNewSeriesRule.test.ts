import { describe, expect, it, vi } from "vitest";
import type { IcsEvent } from "ts-ics";

import type { CalDavService } from "../../../../services/dav/CalDavService";
import { fetchNewSeriesRule } from "../fetchNewSeriesRule";

const utc = (iso: string): Date => new Date(`${iso}Z`);

const makeEvent = (count?: number): IcsEvent => ({
  uid: "uid",
  stamp: { date: utc("2026-09-01T00:00:00") },
  summary: "Event",
  start: { date: utc("2026-10-01T10:00:00"), type: "DATE-TIME" },
  end: { date: utc("2026-10-01T11:00:00"), type: "DATE-TIME" },
  recurrenceRule: { frequency: "WEEKLY", count },
});

const makeService = (result: unknown) => {
  const fetchOccurrenceDates = vi.fn().mockResolvedValue(result);
  return { service: { fetchOccurrenceDates } as unknown as CalDavService, fetchOccurrenceDates };
};

describe("fetchNewSeriesRule", () => {
  it("counts the occurrences that the server expands", async () => {
    const { service, fetchOccurrenceDates } = makeService({
      success: true,
      data: [utc("2026-10-01T10:00:00"), utc("2026-10-08T10:00:00"), utc("2026-10-15T10:00:00")],
    });
    const rule = await fetchNewSeriesRule(
      service,
      "/e.ics",
      makeEvent(8),
      utc("2026-10-15T10:00:00"),
    );
    expect(rule?.count).toBe(6);
    expect(fetchOccurrenceDates).toHaveBeenCalledWith("/e.ics", "uid", expect.anything());
  });

  it("does not call the server for a rule without COUNT", async () => {
    const { service, fetchOccurrenceDates } = makeService({ success: true, data: [] });
    const event = makeEvent();
    const rule = await fetchNewSeriesRule(service, "/e.ics", event, utc("2026-10-15T10:00:00"));
    expect(rule).toBe(event.recurrenceRule);
    expect(fetchOccurrenceDates).not.toHaveBeenCalled();
  });

  it("throws when the server fails", async () => {
    const { service } = makeService({ success: false, error: "boom" });
    await expect(
      fetchNewSeriesRule(service, "/e.ics", makeEvent(8), utc("2026-10-15T10:00:00")),
    ).rejects.toThrow("boom");
  });
});
