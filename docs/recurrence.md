# Recurring Events

Recurring events follow the iCalendar RFC 5545 RRULE standard. No backend
changes are needed — CalDAV (SabreDAV) handles recurrence natively.

## Architecture

```
RecurrenceEditor (React)
  -> IcsRecurrenceRule (ts-ics)
    -> RRULE string (RFC 5545)
      -> .ics file (CalDAV)
        -> SabreDAV server
```

## RecurrenceEditor Component

Located at
`src/frontend/apps/calendars/src/features/calendar/components/RecurrenceEditor.tsx`

```tsx
import { RecurrenceEditor } from '@/features/calendar/components/RecurrenceEditor';

const [recurrence, setRecurrence] = useState<IcsRecurrenceRule>();

<RecurrenceEditor value={recurrence} onChange={setRecurrence} />
```

Include in the event object:

```typescript
const event: IcsEvent = {
  // ...other fields
  recurrenceRule: recurrence,
};
```

### Supported patterns

| Pattern | RRULE |
|---------|-------|
| Every day | `FREQ=DAILY` |
| Every 3 days | `FREQ=DAILY;INTERVAL=3` |
| Every Monday | `FREQ=WEEKLY;BYDAY=MO` |
| Mon/Wed/Fri | `FREQ=WEEKLY;BYDAY=MO,WE,FR` |
| Every 2 weeks on Thu | `FREQ=WEEKLY;INTERVAL=2;BYDAY=TH` |
| 15th of each month | `FREQ=MONTHLY;BYMONTHDAY=15` |
| March 15 yearly | `FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=15` |
| 10 occurrences | append `;COUNT=10` |
| Until a date | append `;UNTIL=20251231T235959Z` |

### Not yet supported

- `BYSETPOS` (e.g. "1st Monday of month", "last Friday")
- Edit single instance vs series (needs RECURRENCE-ID UI)
- Visual preview of recurrence pattern

### Date validation

The component warns about edge cases:
- Feb 30/31 — "February has at most 29 days"
- Feb 29 — "Only exists in leap years"
- Day 31 on 30-day months — shown as warning

### Translations

Supported: English, French, Dutch. Keys are in
`src/frontend/apps/calendars/src/features/i18n/translations.json`
under `calendar.recurrence.*`.

## IcsRecurrenceRule interface (ts-ics)

```typescript
interface IcsRecurrenceRule {
  frequency: 'DAILY' | 'WEEKLY' | 'MONTHLY' | 'YEARLY';
  interval?: number;
  count?: number;
  until?: IcsDateObject;
  byDay?: { day: 'MO'|'TU'|'WE'|'TH'|'FR'|'SA'|'SU' }[];
  byMonthDay?: number[];
  byMonth?: number[];
}
```

## How CalDAV handles it

1. RRULE is stored as a property in the VEVENT inside the `.ics` file
2. SabreDAV expands recurring instances when clients query date ranges
3. Individual instance modifications use RECURRENCE-ID (not yet in UI)

Example `.ics`:

```ics
BEGIN:VEVENT
UID:abc-123
SUMMARY:Weekly Team Meeting
DTSTART:20260125T140000Z
RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261231T235959Z
END:VEVENT
```

## References

- [RFC 5545 — iCalendar](https://datatracker.ietf.org/doc/html/rfc5545)
- [RRULE spec](https://icalendar.org/iCalendar-RFC-5545/3-8-5-3-recurrence-rule.html)
- [ts-ics](https://github.com/Neuvernetzung/ts-ics)
- [SabreDAV](https://sabre.io/dav/)
