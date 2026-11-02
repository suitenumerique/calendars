import { describe, expect, it } from "vitest";

import type { EventCalendarEvent } from "../../../../services/dav/types/event-calendar";
import { createEventContent } from "../eventContent";

const NO_TITLE = "(No title)";
const START = new Date(2026, 0, 29, 9, 0);

const makeEvent = (
  durationMin: number,
  extra: Partial<EventCalendarEvent> = {},
): EventCalendarEvent => ({
  id: "evt-1",
  title: "Standup",
  start: START,
  end: new Date(START.getTime() + durationMin * 60_000),
  ...extra,
});

const render = (event: EventCalendarEvent): string => {
  const content = createEventContent({ event, timeText: "", view: undefined }, NO_TITLE);
  if (typeof content === "string" || !("html" in content)) {
    throw new Error("expected html content");
  }
  return content.html;
};

describe("createEventContent", () => {
  it("shows the start time only for a 30 min event", () => {
    const html = render(makeEvent(30));
    expect(html).toContain("ec-custom--compact");
    expect(html).toContain('<span class="ec-custom__time">09:00</span>');
    expect(html).not.toContain("–");
  });

  it("shows the start and end times for a 45 min event", () => {
    const html = render(makeEvent(45));
    expect(html).toContain("ec-custom--medium");
    expect(html).toContain('<div class="ec-custom__details">09:00 – 09:45</div>');
  });

  it("shows the start and end times for a 90 min event", () => {
    const html = render(makeEvent(90));
    expect(html).toContain("ec-custom--large");
    expect(html).toContain('<div class="ec-custom__details">09:00 – 10:30</div>');
  });

  it("appends the location after the time range", () => {
    const html = render(makeEvent(90, { extendedProps: { location: "Room 1" } }));
    expect(html).toContain('<div class="ec-custom__details">09:00 – 10:30, Room 1</div>');
  });

  it("shows the title only for an all-day event", () => {
    const html = render(makeEvent(90, { allDay: true }));
    expect(html).toContain("ec-custom--allday");
    expect(html).toContain("Standup");
    expect(html).not.toContain("09:00");
  });

  it("falls back to the start time when the end is missing", () => {
    const html = render(makeEvent(0, { end: undefined }));
    expect(html).toContain("ec-custom--compact");
    expect(html).toContain('<span class="ec-custom__time">09:00</span>');
    expect(html).not.toContain("–");
  });
});
