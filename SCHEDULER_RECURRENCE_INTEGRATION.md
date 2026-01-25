# Scheduler Recurrence Integration Guide

## How to Add Recurrence Support to EventModal in Scheduler.tsx

This guide shows exactly how to integrate the RecurrenceEditor component into the existing Scheduler event modal.

## Step 1: Import RecurrenceEditor

Add to imports at the top of `Scheduler.tsx`:

```typescript
import { RecurrenceEditor } from "../RecurrenceEditor";
import type { IcsRecurrenceRule } from "ts-ics";
```

## Step 2: Add Recurrence State

In the `EventModal` component, add recurrence state after the existing useState declarations:

```typescript
// Around line 110, after:
const [attendees, setAttendees] = useState<IcsAttendee[]>([]);
const [showAttendees, setShowAttendees] = useState(false);

// Add:
const [recurrence, setRecurrence] = useState<IcsRecurrenceRule | undefined>(
  event?.recurrenceRule
);
const [showRecurrence, setShowRecurrence] = useState(() => {
  return !!event?.recurrenceRule;
});
```

## Step 3: Reset Recurrence When Event Changes

In the `useEffect` that resets form state, add recurrence reset:

```typescript
// Around line 121-161, in the useEffect(() => { ... }, [event, calendarUrl])
useEffect(() => {
  setTitle(event?.summary || "");
  setDescription(event?.description || "");
  setLocation(event?.location || "");
  setSelectedCalendarUrl(calendarUrl);

  // Initialize attendees from event
  if (event?.attendees && event.attendees.length > 0) {
    setAttendees(event.attendees);
    setShowAttendees(true);
  } else {
    setAttendees([]);
    setShowAttendees(false);
  }

  // ADD THIS: Initialize recurrence from event
  if (event?.recurrenceRule) {
    setRecurrence(event.recurrenceRule);
    setShowRecurrence(true);
  } else {
    setRecurrence(undefined);
    setShowRecurrence(false);
  }

  // ... rest of the useEffect
}, [event, calendarUrl]);
```

## Step 4: Include Recurrence in Save

In the `handleSave` function, add recurrence to the IcsEvent object:

```typescript
// Around line 200-227, when creating the icsEvent
const icsEvent: IcsEvent = {
  ...eventWithoutDuration,
  uid: event?.uid || crypto.randomUUID(),
  summary: title,
  description: description || undefined,
  location: location || undefined,
  start: {
    date: fakeUtcStart,
    local: {
      timezone: BROWSER_TIMEZONE,
      tzoffset: adapter.getTimezoneOffset(startDate, BROWSER_TIMEZONE),
    },
  },
  end: {
    date: fakeUtcEnd,
    local: {
      timezone: BROWSER_TIMEZONE,
      tzoffset: adapter.getTimezoneOffset(endDate, BROWSER_TIMEZONE),
    },
  },
  organizer: organizer,
  attendees: attendees.length > 0 ? attendees : undefined,
  recurrenceRule: recurrence,  // ADD THIS LINE
};
```

## Step 5: Add RecurrenceEditor to UI

In the modal JSX, add a button to show/hide recurrence and the RecurrenceEditor component.

### Add Feature Button (like the attendees button)

Around line 350-360, after the attendees button:

```tsx
{/* Existing code */}
<button
  type="button"
  className={`event-modal__feature-tag ${showAttendees ? 'event-modal__feature-tag--active' : ''}`}
  onClick={() => setShowAttendees(!showAttendees)}
>
  <span className="material-icons">group</span>
  {t('calendar.event.attendees')}
</button>

{/* ADD THIS: Recurrence button */}
<button
  type="button"
  className={`event-modal__feature-tag ${showRecurrence ? 'event-modal__feature-tag--active' : ''}`}
  onClick={() => setShowRecurrence(!showRecurrence)}
>
  <span className="material-icons">repeat</span>
  {t('calendar.recurrence.label')}
</button>
```

### Add RecurrenceEditor Component

Around line 370, after the AttendeesInput:

```tsx
{/* Existing attendees input */}
{showAttendees && (
  <div className="event-modal__attendees-input">
    <AttendeesInput
      attendees={attendees}
      onChange={setAttendees}
      organizerEmail={user?.email}
      organizer={organizer}
    />
  </div>
)}

{/* ADD THIS: Recurrence editor */}
{showRecurrence && (
  <div className="event-modal__recurrence-editor">
    <RecurrenceEditor
      value={recurrence}
      onChange={setRecurrence}
    />
  </div>
)}
```

## Step 6: Add CSS for Recurrence Section

In `Scheduler.scss`, add styling for the recurrence section:

```scss
.event-modal {
  // ... existing styles

  &__recurrence-editor {
    padding: 1rem;
    background-color: #f8f9fa;
    border-radius: 4px;
    margin-top: 1rem;
  }

  // Ensure feature tags wrap properly
  &__features {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;  // Add this if not present
  }
}
```

## Complete EventModal Component Structure

Here's the complete structure with recurrence integrated:

```typescript
const EventModal = ({
  isOpen,
  mode,
  event,
  calendarUrl,
  calendars,
  adapter,
  onSave,
  onDelete,
  onClose,
}: EventModalProps) => {
  const { t } = useTranslation();
  const { user } = useAuth();

  // Form state
  const [title, setTitle] = useState(event?.summary || "");
  const [description, setDescription] = useState(event?.description || "");
  const [location, setLocation] = useState(event?.location || "");
  const [startDateTime, setStartDateTime] = useState("");
  const [endDateTime, setEndDateTime] = useState("");
  const [selectedCalendarUrl, setSelectedCalendarUrl] = useState(calendarUrl);
  const [isLoading, setIsLoading] = useState(false);

  // Features state
  const [attendees, setAttendees] = useState<IcsAttendee[]>([]);
  const [showAttendees, setShowAttendees] = useState(false);
  const [recurrence, setRecurrence] = useState<IcsRecurrenceRule | undefined>();
  const [showRecurrence, setShowRecurrence] = useState(false);

  // Calculate organizer
  const organizer: IcsOrganizer | undefined = event?.organizer || ...;

  // Reset form when event changes
  useEffect(() => {
    // Reset basic fields
    setTitle(event?.summary || "");
    setDescription(event?.description || "");
    setLocation(event?.location || "");
    setSelectedCalendarUrl(calendarUrl);

    // Reset attendees
    if (event?.attendees && event.attendees.length > 0) {
      setAttendees(event.attendees);
      setShowAttendees(true);
    } else {
      setAttendees([]);
      setShowAttendees(false);
    }

    // Reset recurrence
    if (event?.recurrenceRule) {
      setRecurrence(event.recurrenceRule);
      setShowRecurrence(true);
    } else {
      setRecurrence(undefined);
      setShowRecurrence(false);
    }

    // Reset dates
    // ... existing date reset logic
  }, [event, calendarUrl]);

  const handleSave = async () => {
    // ... create icsEvent with recurrence
    const icsEvent: IcsEvent = {
      // ... all fields
      recurrenceRule: recurrence,
    };

    await onSave(icsEvent, selectedCalendarUrl);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose}>
      {/* Title, Calendar selector, Dates */}

      {/* Feature tags */}
      <div className="event-modal__features">
        <button onClick={() => setShowAttendees(!showAttendees)}>
          <span className="material-icons">group</span>
          {t('calendar.event.attendees')}
        </button>

        <button onClick={() => setShowRecurrence(!showRecurrence)}>
          <span className="material-icons">repeat</span>
          {t('calendar.recurrence.label')}
        </button>
      </div>

      {/* Location, Description */}

      {/* Attendees section */}
      {showAttendees && (
        <AttendeesInput
          attendees={attendees}
          onChange={setAttendees}
          organizerEmail={user?.email}
          organizer={organizer}
        />
      )}

      {/* Recurrence section */}
      {showRecurrence && (
        <RecurrenceEditor
          value={recurrence}
          onChange={setRecurrence}
        />
      )}

      {/* Save/Cancel buttons */}
    </Modal>
  );
};
```

## Material Icons

The recurrence button uses the `repeat` Material icon. Make sure Material Icons are loaded:

```html
<!-- In _app.tsx or layout -->
<link
  href="https://fonts.googleapis.com/icon?family=Material+Icons"
  rel="stylesheet"
/>
```

## Testing the Integration

1. **Create new recurring event:**
   - Click "Create" in calendar
   - Click "Repeat" button (🔁 icon)
   - Select "Weekly", check "Monday" and "Wednesday"
   - Save

2. **Edit recurring event:**
   - Click on a recurring event
   - Modal should show recurrence with "Repeat" button active
   - Modify recurrence pattern
   - Save

3. **Remove recurrence:**
   - Open recurring event
   - Click "Repeat" button to expand
   - Select "None" from dropdown
   - Save

## Expected Behavior

- ✅ Recurrence button toggles RecurrenceEditor visibility
- ✅ Active button shows blue background (like attendees)
- ✅ RecurrenceEditor state persists when toggling visibility
- ✅ Saving event includes recurrence in IcsEvent
- ✅ Opening existing recurring event loads recurrence correctly
- ✅ Calendar displays recurring event instances

## Troubleshooting

### Recurrence not saving
- Check that `recurrenceRule: recurrence` is in the icsEvent object
- Verify ts-ics is correctly serializing the RRULE

### Recurrence not loading when editing
- Check the useEffect includes recurrence reset
- Verify event?.recurrenceRule is being passed from EventCalendarAdapter

### UI not showing properly
- Ensure RecurrenceEditor.scss is imported in globals.scss
- Check that Material Icons font is loaded

### Events not appearing as recurring
- Verify CalDAV server supports RRULE
- Check browser console for errors
- Inspect .ics file content in network tab

## Next Steps

After integration, consider:
1. Adding recurrence summary text (e.g., "Repeats weekly on Monday")
2. Handle editing single instance vs series
3. Add "Delete series" vs "Delete this occurrence" options
4. Show recurrence icon in calendar event display
