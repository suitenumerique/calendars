# Recurring Events - Usage Examples

## Real-World Scenarios

This document provides concrete examples of how to use the RecurrenceEditor for common recurring event patterns.

---

## 📅 Example 1: Daily Standup Meeting

**Requirement:** Team standup every weekday (Monday-Friday) at 9:00 AM

### Configuration

```typescript
const recurrence: IcsRecurrenceRule = {
  frequency: 'WEEKLY',
  interval: 1,
  byDay: [
    { day: 'MO' },
    { day: 'TU' },
    { day: 'WE' },
    { day: 'TH' },
    { day: 'FR' }
  ]
};
```

### UI Steps
1. Select "Custom..."
2. Choose "weeks" frequency
3. Click all weekday buttons: M T W T F
4. Leave interval at 1
5. Select "Never" for end condition

### Generated RRULE
```
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
```

---

## 📅 Example 2: Bi-Weekly Sprint Planning

**Requirement:** Sprint planning every 2 weeks on Monday at 10:00 AM for 10 sprints

### Configuration

```typescript
const recurrence: IcsRecurrenceRule = {
  frequency: 'WEEKLY',
  interval: 2,
  byDay: [{ day: 'MO' }],
  count: 10
};
```

### UI Steps
1. Select "Custom..."
2. Set interval to "2"
3. Choose "weeks" frequency
4. Click "M" (Monday)
5. Select "After" and enter "10" occurrences

### Generated RRULE
```
RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;COUNT=10
```

### Resulting Dates (starting Jan 6, 2025)
- Jan 6, 2025
- Jan 20, 2025
- Feb 3, 2025
- Feb 17, 2025
- Mar 3, 2025
- Mar 17, 2025
- Mar 31, 2025
- Apr 14, 2025
- Apr 28, 2025
- May 12, 2025 (last occurrence)

---

## 📅 Example 3: Monthly All-Hands Meeting

**Requirement:** First Monday of each month at 2:00 PM

⚠️ **Note:** "First Monday" pattern requires BYSETPOS (not yet implemented).
**Workaround:** Use specific date if consistent, or create manually each month.

**Alternative - Specific Day of Month:**

### Configuration

```typescript
const recurrence: IcsRecurrenceRule = {
  frequency: 'MONTHLY',
  interval: 1,
  byMonthDay: [5] // 5th of every month
};
```

### UI Steps
1. Select "Custom..."
2. Choose "months" frequency
3. Enter "5" for day of month
4. Select "Never"

### Generated RRULE
```
RRULE:FREQ=MONTHLY;BYMONTHDAY=5
```

---

## 📅 Example 4: Quarterly Business Review

**Requirement:** Last day of March, June, September, December at 3:00 PM

⚠️ **Current Implementation:** Set up as 4 separate yearly events.

**Future Implementation:** Would use BYMONTH with multiple months.

### Configuration (Workaround)

Create 4 separate yearly events:

**Q1 (March 31):**
```typescript
{
  frequency: 'YEARLY',
  interval: 1,
  byMonth: [3],
  byMonthDay: [31]
}
```

**Q2 (June 30):**
```typescript
{
  frequency: 'YEARLY',
  interval: 1,
  byMonth: [6],
  byMonthDay: [30]
}
```

**Q3 (September 30):**
```typescript
{
  frequency: 'YEARLY',
  interval: 1,
  byMonth: [9],
  byMonthDay: [30]
}
```

**Q4 (December 31):**
```typescript
{
  frequency: 'YEARLY',
  interval: 1,
  byMonth: [12],
  byMonthDay: [31]
}
```

---

## 📅 Example 5: Birthday Reminder

**Requirement:** Annual reminder on March 15th

### Configuration

```typescript
const recurrence: IcsRecurrenceRule = {
  frequency: 'YEARLY',
  interval: 1,
  byMonth: [3],
  byMonthDay: [15]
};
```

### UI Steps
1. Select "Custom..."
2. Choose "years" frequency
3. Select "March" from month dropdown
4. Enter "15" for day
5. Select "Never"

### Generated RRULE
```
RRULE:FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=15
```

---

## 📅 Example 6: Payroll Processing

**Requirement:** 1st and 15th of every month

⚠️ **Current Implementation:** Create as 2 separate events:

**First event (1st):**
```typescript
{
  frequency: 'MONTHLY',
  interval: 1,
  byMonthDay: [1]
}
```

**Second event (15th):**
```typescript
{
  frequency: 'MONTHLY',
  interval: 1,
  byMonthDay: [15]
}
```

### UI Steps (for each)
1. Select "Custom..."
2. Choose "months"
3. Enter day (1 or 15)
4. Select "Never"

---

## 📅 Example 7: Project Deadline (Fixed End Date)

**Requirement:** Daily check-ins until project ends on December 31, 2025

### Configuration

```typescript
const recurrence: IcsRecurrenceRule = {
  frequency: 'DAILY',
  interval: 1,
  until: {
    type: 'DATE',
    date: new Date('2025-12-31')
  }
};
```

### UI Steps
1. Select "Custom..."
2. Choose "days" frequency
3. Keep interval at 1
4. Select "On"
5. Choose date: 2025-12-31

### Generated RRULE
```
RRULE:FREQ=DAILY;UNTIL=20251231T235959Z
```

---

## 📅 Example 8: Gym Schedule (Mon/Wed/Fri)

**Requirement:** Gym sessions 3 times per week

### Configuration

```typescript
const recurrence: IcsRecurrenceRule = {
  frequency: 'WEEKLY',
  interval: 1,
  byDay: [
    { day: 'MO' },
    { day: 'WE' },
    { day: 'FR' }
  ]
};
```

### UI Steps
1. Select "Custom..."
2. Choose "weeks"
3. Click M, W, F buttons
4. Select "Never"

### Generated RRULE
```
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR
```

---

## 📅 Example 9: Leap Year Celebration

**Requirement:** February 29th celebration (only on leap years)

### Configuration

```typescript
const recurrence: IcsRecurrenceRule = {
  frequency: 'YEARLY',
  interval: 1,
  byMonth: [2],
  byMonthDay: [29]
};
```

### UI Steps
1. Select "Custom..."
2. Choose "years"
3. Select "February"
4. Enter "29"
5. ⚠️ Warning appears: "This date (Feb 29) only exists in leap years"
6. Select "Never"

### Generated RRULE
```
RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29
```

### Occurrences
- Feb 29, 2024 ✅
- Feb 29, 2028 ✅
- Feb 29, 2032 ✅
- (Skips 2025, 2026, 2027, 2029, 2030, 2031)

---

## 📅 Example 10: Seasonal Team Offsite

**Requirement:** First day of each season (March, June, September, December)

Create 4 separate yearly events or use the pattern:

### Configuration (One event, workaround)

**For March 1:**
```typescript
{
  frequency: 'YEARLY',
  byMonth: [3],
  byMonthDay: [1]
}
```

Repeat for months 6, 9, 12 as separate events.

**Better approach when BYMONTH allows multiple values:**
```typescript
// Future implementation
{
  frequency: 'YEARLY',
  byMonth: [3, 6, 9, 12], // Not yet supported in UI
  byMonthDay: [1]
}
```

---

## 🎯 Complex Patterns Comparison

| Pattern | Status | Implementation |
|---------|--------|----------------|
| "Every day" | ✅ Supported | `FREQ=DAILY` |
| "Every weekday" | ✅ Supported | `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR` |
| "Every Monday" | ✅ Supported | `FREQ=WEEKLY;BYDAY=MO` |
| "1st of every month" | ✅ Supported | `FREQ=MONTHLY;BYMONTHDAY=1` |
| "Last day of month" | ✅ Supported (with caveat) | `FREQ=MONTHLY;BYMONTHDAY=31` |
| "1st Monday of month" | ❌ Future | Needs BYDAY + BYSETPOS |
| "Last Friday of month" | ❌ Future | Needs BYDAY + BYSETPOS=-1 |
| "Every 2 hours" | ❌ Not applicable | Events, not intraday recurrence |

---

## 🧪 Testing Patterns

### Test Case 1: Edge Case - February 30th

```typescript
// User selects:
{
  frequency: 'YEARLY',
  byMonth: [2],
  byMonthDay: [30]
}
```

**Expected:** ⚠️ Warning: "February has at most 29 days"
**Behavior:** Event will never occur (no year has Feb 30)

### Test Case 2: Month Overflow - April 31st

```typescript
// User selects:
{
  frequency: 'MONTHLY',
  byMonthDay: [31]
}
```

**Occurrences:**
- January 31 ✅
- February 31 ❌ (skipped)
- March 31 ✅
- April 31 ❌ (skipped - only 30 days)
- May 31 ✅
- June 31 ❌ (skipped - only 30 days)
- July 31 ✅

**Warning shown for months with 30 days when setting up yearly recurrence**

---

## 📋 Quick Reference

### Frequency Types

```typescript
frequency: 'DAILY'    // Every day
frequency: 'WEEKLY'   // Every week (specify days)
frequency: 'MONTHLY'  // Every month (specify day 1-31)
frequency: 'YEARLY'   // Every year (specify month + day)
```

### Intervals

```typescript
interval: 1  // Every [frequency]
interval: 2  // Every 2 [frequency]
interval: 3  // Every 3 [frequency]
// etc.
```

### Days of Week (WEEKLY)

```typescript
byDay: [
  { day: 'MO' },  // Monday
  { day: 'TU' },  // Tuesday
  { day: 'WE' },  // Wednesday
  { day: 'TH' },  // Thursday
  { day: 'FR' },  // Friday
  { day: 'SA' },  // Saturday
  { day: 'SU' }   // Sunday
]
```

### Day of Month (MONTHLY, YEARLY)

```typescript
byMonthDay: [15]  // 15th of month
byMonthDay: [1]   // 1st of month
byMonthDay: [31]  // 31st of month (with caveats)
```

### Month (YEARLY)

```typescript
byMonth: [1]   // January
byMonth: [2]   // February
// ...
byMonth: [12]  // December
```

### End Conditions

```typescript
// Never ends
(no count or until)

// Ends on date
until: {
  type: 'DATE',
  date: new Date('2025-12-31')
}

// Ends after N occurrences
count: 10
```

---

## 💡 Tips & Best Practices

### 1. Use Simple Mode for Common Patterns

Simple mode is sufficient for:
- Daily recurrence (every day)
- Weekly recurrence (every week, same days)
- Monthly recurrence (same date each month)
- Yearly recurrence (same date each year)

### 2. Use Custom Mode for Advanced Patterns

Custom mode is needed for:
- Intervals > 1 (every 2 weeks, every 3 months)
- Multiple days per week
- End dates or occurrence counts
- Specific validation

### 3. Date Validation

Always check for warnings when selecting:
- February dates (29, 30, 31)
- Month-end dates for monthly recurrence
- Day 31 for months with 30 days

### 4. CalDAV Compatibility

All patterns generated by RecurrenceEditor are standard RRULE format compatible with:
- Apple Calendar
- Google Calendar
- Microsoft Outlook
- Mozilla Thunderbird
- Any RFC 5545 compliant calendar

---

## 🔗 Related Documentation

- [RECURRENCE_IMPLEMENTATION.md](./RECURRENCE_IMPLEMENTATION.md) - Technical implementation
- [SCHEDULER_RECURRENCE_INTEGRATION.md](./SCHEDULER_RECURRENCE_INTEGRATION.md) - Integration guide
- [RECURRENCE_SUMMARY.md](./RECURRENCE_SUMMARY.md) - Quick reference
