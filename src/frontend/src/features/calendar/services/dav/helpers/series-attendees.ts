import type { IcsAttendee, IcsEvent } from "ts-ics";

const emailsOf = (attendees: IcsAttendee[] | undefined): Set<string> =>
  new Set(attendees?.map((a) => a.email.toLowerCase()));

/**
 * Give each attendee that `source` lists the PARTSTAT that `source` has.
 * The other attendees keep their PARTSTAT.
 */
export const withPartstatsFrom = (
  attendees: IcsAttendee[] | undefined,
  source: IcsEvent,
): IcsAttendee[] | undefined =>
  attendees?.map((a) => {
    const email = a.email.toLowerCase();
    const known = source.attendees?.find((s) => s.email.toLowerCase() === email);
    return known ? { ...a, partstat: known.partstat } : a;
  });

/**
 * Apply to an override the attendee change from `oldMaster` to
 * `newMaster`. Remove the attendees that the new master removes. Add the
 * attendees that the new master adds, except to a cancelled override.
 */
export const withSeriesAttendeeChange = (
  override: IcsEvent,
  oldMaster: IcsEvent,
  newMaster: IcsEvent,
): IcsEvent => {
  const before = emailsOf(oldMaster.attendees);
  const after = emailsOf(newMaster.attendees);
  const present = emailsOf(override.attendees);

  const kept = (override.attendees ?? []).filter((a) => {
    const email = a.email.toLowerCase();
    return !before.has(email) || after.has(email);
  });
  const added =
    override.status === "CANCELLED"
      ? []
      : (newMaster.attendees ?? []).filter((a) => {
          const email = a.email.toLowerCase();
          return !before.has(email) && !present.has(email);
        });

  const attendees = [...kept, ...added];
  return { ...override, attendees: attendees.length > 0 ? attendees : undefined };
};
