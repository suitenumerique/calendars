import { describe, expect, it } from "vitest";
import type { IcsEvent } from "ts-ics";

import {
  changeAttendees,
  changeOrganizer,
  isOrganizerCopy,
  mergeAttendeeEdits,
  organizeNewSeries,
  userAddresses,
} from "../organizer";

const meeting = (organizer: string, ...attendees: string[]): IcsEvent =>
  ({
    uid: "uid",
    summary: "Meeting",
    stamp: { date: new Date() },
    start: { date: new Date() },
    organizer: { email: organizer },
    attendees: attendees.map((email) => ({ email, partstat: "NEEDS-ACTION" })),
  }) as IcsEvent;

describe("isOrganizerCopy", () => {
  it("is true when the calendar identity organizes the event", () => {
    expect(isOrganizerCopy(meeting("team@x.fr", "ext@y.fr"), "team@x.fr", [])).toBe(true);
  });

  it("is false when the calendar identity is an attendee", () => {
    const event = meeting("team@x.fr", "me@x.fr");
    expect(isOrganizerCopy(event, "me@x.fr", ["me@x.fr", "team@x.fr"])).toBe(false);
  });

  it("uses the user addresses when the event does not contain the identity", () => {
    const event = meeting("team@x.fr", "ext@y.fr");
    expect(isOrganizerCopy(event, "me@x.fr", ["me@x.fr", "team@x.fr"])).toBe(true);
    expect(isOrganizerCopy(event, "me@x.fr", ["me@x.fr"])).toBe(false);
  });

  it("is true for an event without organizer", () => {
    expect(isOrganizerCopy({ uid: "uid" } as IcsEvent, "me@x.fr", [])).toBe(true);
  });
});

describe("changeOrganizer", () => {
  it("only sets the organizer when it does not change", () => {
    const event = meeting("team@x.fr", "ext@y.fr");
    expect(changeOrganizer(event, { email: "TEAM@x.fr" }, event.organizer)).toEqual({
      ...event,
      organizer: { email: "TEAM@x.fr" },
    });
  });

  it("makes the previous organizer an attendee that accepts", () => {
    const event = meeting("team@x.fr", "ext@y.fr", "me@x.fr");
    const changed = changeOrganizer(event, { email: "me@x.fr" }, event.organizer);
    expect(changed.organizer).toEqual({ email: "me@x.fr" });
    expect(changed.attendees).toEqual([
      { email: "ext@y.fr", partstat: "NEEDS-ACTION" },
      { email: "team@x.fr", name: undefined, partstat: "ACCEPTED" },
    ]);
  });

  it("only sets the organizer without a previous organizer", () => {
    const event = { ...meeting("team@x.fr"), attendees: undefined };
    expect(changeOrganizer(event, { email: "me@x.fr" }, undefined)).toEqual({
      ...event,
      organizer: { email: "me@x.fr" },
    });
  });

  it("keeps the previous organizer when no guest is left", () => {
    const event = meeting("team@x.fr");
    const changed = changeOrganizer(event, { email: "me@x.fr" }, { email: "team@x.fr" });
    expect(changed.attendees).toEqual([
      { email: "team@x.fr", name: undefined, partstat: "ACCEPTED" },
    ]);
  });
});

describe("organizeNewSeries", () => {
  it("does not make the previous organizer an attendee", () => {
    const event = meeting("me@x.fr", "ext@y.fr", "TEAM@x.fr");
    const series = organizeNewSeries(event, { email: "team@x.fr" }, event.organizer);
    expect(series.organizer).toEqual({ email: "team@x.fr" });
    expect(series.attendees).toEqual([{ email: "ext@y.fr", partstat: "NEEDS-ACTION" }]);
  });

  it("removes the previous organizer from the attendees", () => {
    const event = meeting("me@x.fr", "ME@x.fr", "ext@y.fr");
    const series = organizeNewSeries(event, { email: "team@x.fr" }, event.organizer);
    expect(series.attendees).toEqual([{ email: "ext@y.fr", partstat: "NEEDS-ACTION" }]);
  });
});

describe("mergeAttendeeEdits", () => {
  const organizer = { email: "me@x.fr" };
  const previous = { email: "team@x.fr" };

  it("keeps the hidden new organizer after an edit", () => {
    const current = meeting("team@x.fr", "me@x.fr").attendees!;
    const shown = changeAttendees(current, organizer, previous);
    const edited = [...shown, { email: "new@y.fr" }];

    const result = mergeAttendeeEdits(edited, current, organizer, previous);

    expect(result.map((a) => a.email)).toEqual(["new@y.fr", "me@x.fr"]);
  });

  it("does not keep the previous organizer", () => {
    const current = meeting("team@x.fr", "ext@y.fr").attendees!;
    const shown = changeAttendees(current, organizer, previous);

    const result = mergeAttendeeEdits(shown, current, organizer, previous);

    expect(result.map((a) => a.email)).toEqual(["ext@y.fr"]);
  });
});

describe("userAddresses", () => {
  it("keeps the mailboxes that the user can write to, hidden or not", () => {
    const calendars = [
      { mailboxEmail: "team@x.fr" },
      { mailboxEmail: "hidden@x.fr", hidden: true },
      { mailboxEmail: "read@x.fr", readOnly: true },
      {},
    ];
    expect(userAddresses("me@x.fr", calendars)).toEqual(["me@x.fr", "team@x.fr", "hidden@x.fr"]);
  });

  it("treats a meeting of a read-only mailbox as a guest copy", () => {
    const addresses = userAddresses("me@x.fr", [{ mailboxEmail: "read@x.fr", readOnly: true }]);
    expect(isOrganizerCopy(meeting("read@x.fr", "ext@y.fr"), "me@x.fr", addresses)).toBe(false);
  });
});
