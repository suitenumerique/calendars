# Recurring Events Implementation Guide

## Overview

This document describes the complete implementation of recurring events in the CalDAV calendar application. The implementation follows the iCalendar RFC 5545 standard for RRULE (Recurrence Rule).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                    │
├─────────────────────────────────────────────────────────────┤
│  RecurrenceEditor Component                                  │
│  ├─ UI for frequency selection (DAILY/WEEKLY/MONTHLY/YEARLY) │
│  ├─ Interval input                                          │
│  ├─ Day/Month/Date selection                                │
│  └─ End conditions (never/until/count)                      │
│                                                              │
│  EventCalendarAdapter                                        │
│  ├─ Converts IcsRecurrenceRule to RRULE string             │
│  └─ Parses RRULE to IcsRecurrenceRule                      │
├─────────────────────────────────────────────────────────────┤
│                         ts-ics Library                       │
│  IcsRecurrenceRule interface                                │
│  ├─ frequency: 'DAILY' | 'WEEKLY' | 'MONTHLY' | 'YEARLY'   │
│  ├─ interval?: number                                       │
│  ├─ byDay?: IcsWeekDay[]                                    │
│  ├─ byMonthDay?: number[]                                   │
│  ├─ byMonth?: number[]                                      │
│  ├─ count?: number                                          │
│  └─ until?: IcsDateObject                                   │
├─────────────────────────────────────────────────────────────┤
│                       CalDAV Protocol                        │
│  RRULE property in VEVENT                                   │
│  Example: RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR         │
├─────────────────────────────────────────────────────────────┤
│                    Sabre/dav Server (PHP)                    │
│  Stores and serves iCalendar (.ics) files                   │
│  Handles recurring event expansion                          │
└─────────────────────────────────────────────────────────────┘
```

## Component Structure

### RecurrenceEditor Component

Location: `src/features/calendar/components/RecurrenceEditor.tsx`

**Props:**
```typescript
interface RecurrenceEditorProps {
  value?: IcsRecurrenceRule;
  onChange: (rule: IcsRecurrenceRule | undefined) => void;
}
```

**Features:**
- ✅ Simple mode: Quick selection (None, Daily, Weekly, Monthly, Yearly)
- ✅ Custom mode: Full control over all recurrence parameters
- ✅ DAILY: Interval support (every X days)
- ✅ WEEKLY: Interval + day selection (MO, TU, WE, TH, FR, SA, SU)
- ✅ MONTHLY: Day of month (1-31) with validation
- ✅ YEARLY: Month + day selection with leap year support
- ✅ End conditions: Never / Until date / After N occurrences
- ✅ Date validation warnings (Feb 30th, Feb 29th leap year, etc.)

### Example Usage

```tsx
import { RecurrenceEditor } from '@/features/calendar/components/RecurrenceEditor';
import { useState } from 'react';
import type { IcsRecurrenceRule } from 'ts-ics';

function EventForm() {
  const [recurrence, setRecurrence] = useState<IcsRecurrenceRule | undefined>();

  return (
    <form>
      {/* Other event fields */}

      <RecurrenceEditor
        value={recurrence}
        onChange={setRecurrence}
      />

      {/* Save button */}
    </form>
  );
}
```

## Integration with Scheduler

To integrate the RecurrenceEditor into the existing Scheduler modal, add the following:

### 1. Add recurrence state

```typescript
// In EventModal component
const [recurrence, setRecurrence] = useState<IcsRecurrenceRule | undefined>(
  event?.recurrenceRule
);
```

### 2. Add RecurrenceEditor to the form

```tsx
import { RecurrenceEditor } from '../RecurrenceEditor';

// In the modal JSX, after location/description fields
<RecurrenceEditor
  value={recurrence}
  onChange={setRecurrence}
/>
```

### 3. Include recurrence in event save

```typescript
const icsEvent: IcsEvent = {
  // ... existing fields
  recurrenceRule: recurrence,
};
```

### 4. Reset recurrence when modal opens

```typescript
useEffect(() => {
  // ... existing resets
  setRecurrence(event?.recurrenceRule);
}, [event]);
```

## RRULE Examples

### Daily Recurrence

**Every day:**
```
RRULE:FREQ=DAILY;INTERVAL=1
```

**Every 3 days:**
```
RRULE:FREQ=DAILY;INTERVAL=3
```

**Daily for 10 occurrences:**
```
RRULE:FREQ=DAILY;COUNT=10
```

**Daily until Dec 31, 2025:**
```
RRULE:FREQ=DAILY;UNTIL=20251231T235959Z
```

### Weekly Recurrence

**Every week on Monday:**
```
RRULE:FREQ=WEEKLY;BYDAY=MO
```

**Every 2 weeks on Monday and Friday:**
```
RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR
```

**Weekly on weekdays (Mon-Fri):**
```
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
```

### Monthly Recurrence

**Every month on the 15th:**
```
RRULE:FREQ=MONTHLY;BYMONTHDAY=15
```

**Every 3 months on the 1st:**
```
RRULE:FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=1
```

**Monthly on the last day (31st with fallback):**
```
RRULE:FREQ=MONTHLY;BYMONTHDAY=31
```
Note: For months with fewer than 31 days, most implementations skip that occurrence.

### Yearly Recurrence

**Every year on March 15th:**
```
RRULE:FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=15
```

**Every year on February 29th (leap years only):**
```
RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29
```

**Every 2 years on December 25th:**
```
RRULE:FREQ=YEARLY;INTERVAL=2;BYMONTH=12;BYMONTHDAY=25
```

## Date Validation

The RecurrenceEditor includes smart validation for invalid dates:

### February 30th/31st
**Warning:** "February has at most 29 days"

### February 29th
**Warning:** "This date (Feb 29) only exists in leap years"

### April 31st, June 31st, etc.
**Warning:** "This month has at most 30 days"

### Day > 31
**Warning:** "Day must be between 1 and 31"

## IcsRecurrenceRule Interface (ts-ics)

```typescript
interface IcsRecurrenceRule {
  frequency: 'DAILY' | 'WEEKLY' | 'MONTHLY' | 'YEARLY';
  interval?: number;              // Default: 1
  count?: number;                 // Number of occurrences
  until?: IcsDateObject;          // End date
  byDay?: IcsWeekDay[];          // Days of week (WEEKLY)
  byMonthDay?: number[];         // Days of month (MONTHLY, YEARLY)
  byMonth?: number[];            // Months (YEARLY)
  bySetPos?: number[];           // Position (e.g., 1st Monday)
  weekStart?: IcsWeekDay;        // Week start day
}

type IcsWeekDay = 'MO' | 'TU' | 'WE' | 'TH' | 'FR' | 'SA' | 'SU';
```

## Backend Considerations

The Django backend **does not need modifications** for recurring events. CalDAV handles recurrence natively:

1. **Storage:** RRULE is stored as a property in the VEVENT within the .ics file
2. **Expansion:** Sabre/dav handles recurring event expansion when clients query date ranges
3. **Modifications:** Individual instances can be modified by creating exception events with RECURRENCE-ID

### Example .ics file with recurrence

```ics
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//CalDavService//NONSGML v1.0//EN
METHOD:PUBLISH
BEGIN:VEVENT
UID:abc-123-def-456
DTSTART:20260125T140000Z
DTEND:20260125T150000Z
SUMMARY:Weekly Team Meeting
RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261231T235959Z
ORGANIZER;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob;PARTSTAT=NEEDS-ACTION:mailto:bob@example.com
END:VEVENT
END:VCALENDAR
```

## Testing

### Manual Testing Checklist

- [ ] Daily recurrence with interval 1, 3, 7
- [ ] Weekly recurrence with single day (Monday)
- [ ] Weekly recurrence with multiple days (Mon, Wed, Fri)
- [ ] Weekly recurrence with interval 2
- [ ] Monthly recurrence on day 1, 15, 31
- [ ] Monthly recurrence with February validation
- [ ] Yearly recurrence on Jan 1, Dec 25
- [ ] Yearly recurrence on Feb 29 with leap year warning
- [ ] Never-ending recurrence
- [ ] Until date recurrence
- [ ] Count-based recurrence (10 occurrences)
- [ ] Edit recurring event
- [ ] Delete recurring event

### Test Cases

```typescript
// Test: Weekly on Monday and Friday
const rule: IcsRecurrenceRule = {
  frequency: 'WEEKLY',
  interval: 1,
  byDay: [{ day: 'MO' }, { day: 'FR' }],
};
// Expected RRULE: FREQ=WEEKLY;BYDAY=MO,FR

// Test: Monthly on 31st (handles months with fewer days)
const rule: IcsRecurrenceRule = {
  frequency: 'MONTHLY',
  interval: 1,
  byMonthDay: [31],
};
// Expected RRULE: FREQ=MONTHLY;BYMONTHDAY=31

// Test: Yearly on Feb 29
const rule: IcsRecurrenceRule = {
  frequency: 'YEARLY',
  interval: 1,
  byMonth: [2],
  byMonthDay: [29],
  count: 10,
};
// Expected RRULE: FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29;COUNT=10
```

## Translations

All UI strings are internationalized (i18n) with support for:
- 🇬🇧 English
- 🇫🇷 French
- 🇳🇱 Dutch

Translation keys are defined in `src/features/i18n/translations.json`:

```json
{
  "calendar": {
    "recurrence": {
      "label": "Repeat",
      "daily": "Daily",
      "weekly": "Weekly",
      "monthly": "Monthly",
      "yearly": "Yearly",
      "repeatOnDay": "Repeat on day",
      "repeatOnDate": "Repeat on date",
      "dayOfMonth": "Day",
      "months": {
        "january": "January",
        "february": "February",
        ...
      },
      "warnings": {
        "februaryMax": "February has at most 29 days",
        "leapYear": "This date (Feb 29) only exists in leap years",
        ...
      }
    }
  }
}
```

## Styling

Styles are in `RecurrenceEditor.scss` using BEM methodology:

```scss
.recurrence-editor {
  &__label { ... }
  &__weekday-button { ... }
  &__weekday-button--selected { ... }
  &__warning { ... }
}

.recurrence-editor-layout {
  &--row { ... }
  &--gap-1rem { ... }
  &--flex-wrap { ... }
}
```

## Known Limitations

1. **No BYDAY with position** (e.g., "2nd Tuesday of month")
   - Future enhancement
   - Requires UI for "1st/2nd/3rd/4th/last" + weekday selection

2. **No BYSETPOS** (complex patterns)
   - e.g., "Last Friday of every month"
   - Requires advanced UI

3. **Time zone handling**
   - UNTIL dates are converted to UTC
   - Local time events use floating time

4. **Recurring event modifications**
   - Editing single instance creates exception (RECURRENCE-ID)
   - Not yet implemented in UI (future work)

## Future Enhancements

- [ ] Visual calendar preview of recurrence pattern
- [ ] Natural language summary ("Every 2 weeks on Monday and Friday")
- [ ] Support for BYSETPOS (nth occurrence patterns)
- [ ] Exception handling UI for editing single instances
- [ ] Recurring event series deletion options (this only / this and future / all)

## References

- [RFC 5545 - iCalendar](https://datatracker.ietf.org/doc/html/rfc5545)
- [RRULE Specification](https://icalendar.org/iCalendar-RFC-5545/3-8-5-3-recurrence-rule.html)
- [ts-ics Documentation](https://github.com/Neuvernetzung/ts-ics)
- [Sabre/dav Documentation](https://sabre.io/dav/)
