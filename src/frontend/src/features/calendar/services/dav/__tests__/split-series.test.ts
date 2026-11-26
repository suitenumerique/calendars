/**
 * splitSeries builds the new series of a "this and future" edit.
 */
import { convertIcsCalendar, type IcsEvent } from "ts-ics";
import { splitSeries } from "../helpers/split-series";

// A weekly series at 09:00 in Paris, from 2026-12-03. The guest declines
// 2026-12-17 only. The date of 2026-12-24 moves to 11:00. The date of
// 2026-12-31 is deleted. The guest answers "maybe" for 2027-01-07 only.
const ICS = [
  "BEGIN:VCALENDAR",
  "VERSION:2.0",
  "PRODID:-//test//EN",
  "BEGIN:VEVENT",
  "UID:old",
  "DTSTAMP:20261101T000000Z",
  "DTSTART;TZID=Europe/Paris:20261203T090000",
  "DTEND;TZID=Europe/Paris:20261203T100000",
  "RRULE:FREQ=WEEKLY",
  "EXDATE;TZID=Europe/Paris:20261231T090000",
  "SUMMARY:Weekly",
  "ORGANIZER:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=ACCEPTED:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=ACCEPTED:mailto:guest@x.test",
  "END:VEVENT",
  "BEGIN:VEVENT",
  "UID:old",
  "DTSTAMP:20261101T000000Z",
  "RECURRENCE-ID;TZID=Europe/Paris:20261217T090000",
  "DTSTART;TZID=Europe/Paris:20261217T090000",
  "DTEND;TZID=Europe/Paris:20261217T100000",
  "SUMMARY:Weekly",
  "ORGANIZER:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=ACCEPTED:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=DECLINED:mailto:guest@x.test",
  "END:VEVENT",
  "BEGIN:VEVENT",
  "UID:old",
  "DTSTAMP:20261101T000000Z",
  "RECURRENCE-ID:20261224T080000Z",
  "DTSTART;TZID=Europe/Paris:20261224T110000",
  "DTEND;TZID=Europe/Paris:20261224T120000",
  "SUMMARY:Weekly (moved)",
  "ORGANIZER:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=ACCEPTED:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:guest@x.test",
  "END:VEVENT",
  "BEGIN:VEVENT",
  "UID:old",
  "DTSTAMP:20261101T000000Z",
  "RECURRENCE-ID;TZID=Europe/Paris:20270107T090000",
  "DTSTART;TZID=Europe/Paris:20270107T090000",
  "DTEND;TZID=Europe/Paris:20270107T100000",
  "SUMMARY:Weekly (answer)",
  "ORGANIZER:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=ACCEPTED:mailto:org@x.test",
  "ATTENDEE;PARTSTAT=TENTATIVE:mailto:guest@x.test",
  "END:VEVENT",
  "END:VCALENDAR",
].join("\r\n");

const wall = (day: number, hours: number): Date => new Date(Date.UTC(2026, 11, day, hours));

const source = (): IcsEvent[] => convertIcsCalendar(undefined, ICS).events!;

/** The edited occurrence of 2026-12-17, moved from 09:00 to 10:00. */
const edited = (events: IcsEvent[]): IcsEvent => {
  const override = events.find((e) => e.recurrenceId?.value.local?.date.getUTCDate() === 17)!;
  const at = (date: Date) => ({
    ...override.start,
    date,
    local: { ...override.start.local!, date },
  });
  return {
    ...override,
    uid: "new",
    recurrenceId: undefined,
    recurrenceRule: { frequency: "WEEKLY" },
    start: at(wall(17, 10)),
    end: at(wall(17, 11)),
  } as IcsEvent;
};

const partstatOf = (event: IcsEvent, email: string) =>
  event.attendees?.find((a) => a.email === email)?.partstat;

describe("splitSeries", () => {
  it("gives the new series the PARTSTAT of the old master", () => {
    const events = source();
    const master = events.find((e) => !e.recurrenceId)!;

    const result = splitSeries(events, master, edited(events), wall(17, 9));

    expect(partstatOf(result.master, "guest@x.test")).toBe("ACCEPTED");
  });

  it("keeps the answer for the edited date on the first date only", () => {
    const events = source();
    const master = events.find((e) => !e.recurrenceId)!;

    const { overrides } = splitSeries(events, master, edited(events), wall(17, 9));

    const first = overrides.find(
      (e) => e.recurrenceId?.value.date.getTime() === wall(17, 10).getTime(),
    );
    expect(first).toBeDefined();
    expect(first!.recurrenceRule).toBeUndefined();
    expect(partstatOf(first!, "guest@x.test")).toBe("DECLINED");
  });

  it("moves the later overrides and EXDATEs with the new start", () => {
    const events = source();
    const master = events.find((e) => !e.recurrenceId)!;

    const result = splitSeries(events, master, edited(events), wall(17, 9));

    const moved = result.overrides.find((e) => e.summary === "Weekly (moved)")!;
    expect(moved.uid).toBe("new");
    expect(moved.recurrenceId!.value.local).toMatchObject({
      date: wall(24, 10),
      timezone: "Europe/Paris",
    });
    expect(moved.start.local?.date).toEqual(wall(24, 11));
    expect(result.master.exceptionDates?.map((d) => d.local?.date)).toEqual([wall(31, 10)]);
  });

  it("moves an override at its own date with the new start", () => {
    const events = source();
    const master = events.find((e) => !e.recurrenceId)!;

    const result = splitSeries(events, master, edited(events), wall(17, 9));

    const answer = result.overrides.find((e) => e.summary === "Weekly (answer)")!;
    const jan7 = new Date(Date.UTC(2027, 0, 7, 10));
    expect(answer.recurrenceId!.value.local?.date).toEqual(jan7);
    expect(answer.start.local?.date).toEqual(jan7);
    expect(partstatOf(answer, "guest@x.test")).toBe("TENTATIVE");
  });

  it("applies the attendee change to the moved overrides", () => {
    const events = source();
    const master = events.find((e) => !e.recurrenceId)!;
    const next: IcsEvent = {
      ...edited(events),
      attendees: [
        { email: "org@x.test", partstat: "ACCEPTED" },
        { email: "new@x.test", partstat: "NEEDS-ACTION" },
      ],
    };

    const result = splitSeries(events, master, next, wall(17, 9));

    for (const override of result.overrides) {
      expect(override.attendees?.map((a) => a.email)).toEqual(["org@x.test", "new@x.test"]);
    }
  });

  it("adds no override when the edited date has no own answer", () => {
    const events = source().filter((e) => e.summary !== "Weekly (moved)");
    const master = events.find((e) => !e.recurrenceId)!;
    const next: IcsEvent = { ...edited(events), attendees: master.attendees };
    const withoutEdited = events.filter((e) => !e.recurrenceId);

    const result = splitSeries(withoutEdited, master, next, wall(17, 9));

    expect(result.overrides).toEqual([]);
  });
});
