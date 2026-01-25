/**
 * Types for EventCalendar adapter (vkurko/calendar)
 *
 * Based on: https://github.com/vkurko/calendar
 * These types represent the EventCalendar library format
 */

// ============================================================================
// Duration Types
// ============================================================================

export type EventCalendarDuration = {
  years?: number
  months?: number
  weeks?: number
  days?: number
  hours?: number
  minutes?: number
  seconds?: number
}

export type EventCalendarDurationInput =
  | EventCalendarDuration
  | string // 'hh:mm:ss' or 'hh:mm'
  | number // total seconds

// ============================================================================
// Event Types
// ============================================================================

export type EventCalendarEvent = {
  id: string | number
  resourceId?: string | number
  resourceIds?: (string | number)[]
  allDay?: boolean
  start: Date | string
  end?: Date | string
  title?: EventCalendarContent
  editable?: boolean
  startEditable?: boolean
  durationEditable?: boolean
  display?: 'auto' | 'background' | 'ghost' | 'preview' | 'pointer'
  backgroundColor?: string
  textColor?: string
  color?: string
  classNames?: string | string[]
  styles?: string | string[]
  extendedProps?: Record<string, unknown>
}

export type EventCalendarEventInput = Omit<EventCalendarEvent, 'id'> & {
  id?: string | number
}

// ============================================================================
// Resource Types
// ============================================================================

export type EventCalendarResource = {
  id: string | number
  title?: EventCalendarContent
  eventBackgroundColor?: string
  eventTextColor?: string
  extendedProps?: Record<string, unknown>
  children?: EventCalendarResource[]
}

// ============================================================================
// View Types
// ============================================================================

export type EventCalendarView =
  | 'dayGridMonth'
  | 'dayGridWeek'
  | 'dayGridDay'
  | 'timeGridWeek'
  | 'timeGridDay'
  | 'listDay'
  | 'listWeek'
  | 'listMonth'
  | 'listYear'
  | 'resourceTimeGridDay'
  | 'resourceTimeGridWeek'
  | 'resourceTimelineDay'
  | 'resourceTimelineWeek'
  | 'resourceTimelineMonth'

export type EventCalendarViewInfo = {
  type: EventCalendarView
  title: string
  currentStart: Date
  currentEnd: Date
  activeStart: Date
  activeEnd: Date
}

// ============================================================================
// Content Types
// ============================================================================

export type EventCalendarContent =
  | string
  | { html: string }
  | { domNodes: Node[] }

// ============================================================================
// Callback/Handler Types
// ============================================================================

// Note: jsEvent uses Event (not MouseEvent) for compatibility with @event-calendar/core DomEvent type
export type EventCalendarEventClickInfo = {
  el: HTMLElement
  event: EventCalendarEvent
  jsEvent: Event
  view: EventCalendarViewInfo
}

export type EventCalendarDateClickInfo = {
  date: Date
  dateStr: string
  allDay: boolean
  dayEl: HTMLElement
  jsEvent: Event
  view: EventCalendarViewInfo
  resource?: EventCalendarResource
}

export type EventCalendarEventDropInfo = {
  event: EventCalendarEvent
  oldEvent: EventCalendarEvent
  oldResource?: EventCalendarResource
  newResource?: EventCalendarResource
  delta: EventCalendarDuration
  revert: () => void
  jsEvent: Event
  view: EventCalendarViewInfo
}

export type EventCalendarEventResizeInfo = {
  event: EventCalendarEvent
  oldEvent: EventCalendarEvent
  startDelta: EventCalendarDuration
  endDelta: EventCalendarDuration
  revert: () => void
  jsEvent: Event
  view: EventCalendarViewInfo
}

export type EventCalendarSelectInfo = {
  start: Date
  end: Date
  startStr: string
  endStr: string
  allDay: boolean
  jsEvent: Event
  view: EventCalendarViewInfo
  resource?: EventCalendarResource
}

export type EventCalendarDatesSetInfo = {
  start: Date
  end: Date
  startStr: string
  endStr: string
  view: EventCalendarViewInfo
}

export type EventCalendarEventMountInfo = {
  el: HTMLElement
  event: EventCalendarEvent
  view: EventCalendarViewInfo
  timeText: string
}

export type EventCalendarEventContentInfo = {
  event: EventCalendarEvent
  view: EventCalendarViewInfo
  timeText: string
}

// ============================================================================
// Options Types
// ============================================================================

export type EventCalendarOptions = {
  // View configuration
  view?: EventCalendarView
  views?: Record<string, EventCalendarViewOptions>
  headerToolbar?: EventCalendarToolbar
  footerToolbar?: EventCalendarToolbar

  // Date configuration
  date?: Date | string
  firstDay?: 0 | 1 | 2 | 3 | 4 | 5 | 6
  hiddenDays?: number[]

  // Time configuration
  slotMinTime?: EventCalendarDurationInput
  slotMaxTime?: EventCalendarDurationInput
  slotDuration?: EventCalendarDurationInput
  slotLabelInterval?: EventCalendarDurationInput
  slotHeight?: number
  scrollTime?: EventCalendarDurationInput

  // Display configuration
  allDaySlot?: boolean
  allDayContent?: EventCalendarContent
  dayMaxEvents?: boolean | number
  nowIndicator?: boolean
  locale?: string

  // Event configuration
  events?: EventCalendarEvent[] | EventCalendarEventFetcher
  eventSources?: EventCalendarEventSource[]
  eventColor?: string
  eventBackgroundColor?: string
  eventTextColor?: string
  eventClassNames?: string | string[] | ((info: EventCalendarEventMountInfo) => string | string[])
  eventContent?: EventCalendarContent | ((info: EventCalendarEventContentInfo) => EventCalendarContent)
  displayEventEnd?: boolean

  // Resource configuration
  resources?: EventCalendarResource[] | EventCalendarResourceFetcher
  datesAboveResources?: boolean
  filterResourcesWithEvents?: boolean

  // Interaction configuration
  editable?: boolean
  selectable?: boolean
  dragScroll?: boolean
  eventStartEditable?: boolean
  eventDurationEditable?: boolean
  eventDragMinDistance?: number
  longPressDelay?: number

  // Callbacks
  dateClick?: (info: EventCalendarDateClickInfo) => void
  eventClick?: (info: EventCalendarEventClickInfo) => void
  eventDrop?: (info: EventCalendarEventDropInfo) => void
  eventResize?: (info: EventCalendarEventResizeInfo) => void
  select?: (info: EventCalendarSelectInfo) => void
  datesSet?: (info: EventCalendarDatesSetInfo) => void
  eventDidMount?: (info: EventCalendarEventMountInfo) => void

  // Button text
  buttonText?: {
    today?: string
    dayGridMonth?: string
    dayGridWeek?: string
    dayGridDay?: string
    listDay?: string
    listWeek?: string
    listMonth?: string
    listYear?: string
    resourceTimeGridDay?: string
    resourceTimeGridWeek?: string
    resourceTimelineDay?: string
    resourceTimelineWeek?: string
    resourceTimelineMonth?: string
    timeGridDay?: string
    timeGridWeek?: string
  }

  // Theme
  theme?: EventCalendarTheme
}

export type EventCalendarViewOptions = Partial<EventCalendarOptions> & {
  titleFormat?: ((start: Date, end: Date) => string) | Intl.DateTimeFormatOptions
  duration?: EventCalendarDurationInput
  dayHeaderFormat?: Intl.DateTimeFormatOptions
  slotLabelFormat?: Intl.DateTimeFormatOptions
}

export type EventCalendarToolbar = {
  start?: string
  center?: string
  end?: string
}

export type EventCalendarTheme = {
  allDay?: string
  active?: string
  bgEvent?: string
  bgEvents?: string
  body?: string
  button?: string
  buttonGroup?: string
  calendar?: string
  compact?: string
  content?: string
  day?: string
  dayFoot?: string
  dayHead?: string
  daySide?: string
  days?: string
  draggable?: string
  dragging?: string
  event?: string
  eventBody?: string
  eventTag?: string
  eventTime?: string
  eventTitle?: string
  events?: string
  extra?: string
  ghost?: string
  handle?: string
  header?: string
  hiddenScroll?: string
  hiddenTimes?: string
  highlight?: string
  icon?: string
  line?: string
  lines?: string
  list?: string
  month?: string
  noEvents?: string
  nowIndicator?: string
  otherMonth?: string
  pointer?: string
  popup?: string
  preview?: string
  resizer?: string
  resource?: string
  resourceTitle?: string
  sidebar?: string
  today?: string
  time?: string
  title?: string
  toolbar?: string
  view?: string
  week?: string
  withScroll?: string
}

// ============================================================================
// Event Source Types
// ============================================================================

export type EventCalendarEventSource = {
  events?: EventCalendarEvent[] | EventCalendarEventFetcher
  url?: string
  method?: string
  extraParams?: Record<string, unknown> | (() => Record<string, unknown>)
  eventDataTransform?: (event: unknown) => EventCalendarEventInput
  backgroundColor?: string
  textColor?: string
  color?: string
  classNames?: string | string[]
  editable?: boolean
}

export type EventCalendarFetchInfo = {
  start: Date
  end: Date
  startStr: string
  endStr: string
}

export type EventCalendarEventFetcher = (
  fetchInfo: EventCalendarFetchInfo,
  successCallback: (events: EventCalendarEventInput[]) => void,
  failureCallback: (error: Error) => void
) => void | Promise<EventCalendarEventInput[]>

export type EventCalendarResourceFetcher = (
  fetchInfo: EventCalendarFetchInfo,
  successCallback: (resources: EventCalendarResource[]) => void,
  failureCallback: (error: Error) => void
) => void | Promise<EventCalendarResource[]>

// ============================================================================
// Calendar Instance Types
// ============================================================================

export type EventCalendarInstance = {
  // Navigation
  getDate(): Date
  setOption(name: string, value: unknown): void
  getOption(name: string): unknown
  getView(): EventCalendarViewInfo
  prev(): void
  next(): void
  today(): void
  gotoDate(date: Date | string): void

  // Events
  getEvents(): EventCalendarEvent[]
  getEventById(id: string | number): EventCalendarEvent | null
  addEvent(event: EventCalendarEventInput): EventCalendarEvent
  updateEvent(event: EventCalendarEvent): void
  removeEventById(id: string | number): void
  refetchEvents(): void

  // Resources
  getResources(): EventCalendarResource[]
  getResourceById(id: string | number): EventCalendarResource | null
  addResource(resource: EventCalendarResource): void
  refetchResources(): void

  // Rendering
  unselect(): void
  destroy(): void
}

// ============================================================================
// Conversion Options
// ============================================================================

export type CalDavToEventCalendarOptions = {
  /** Default color for events without a color */
  defaultEventColor?: string
  /** Default text color for events */
  defaultTextColor?: string
  /** Whether to include recurring event instances */
  includeRecurringInstances?: boolean
  /** Custom ID generator for events */
  eventIdGenerator?: (event: unknown, calendarUrl: string) => string | number
  /** Custom extended props extractor */
  extendedPropsExtractor?: (event: unknown) => Record<string, unknown>
  /** Map calendar URLs to colors */
  calendarColors?: Map<string, string>
}

export type EventCalendarToCalDavOptions = {
  /** Default calendar URL for new events */
  defaultCalendarUrl?: string
  /** Default timezone for events */
  defaultTimezone?: string
  /** Custom UID generator */
  uidGenerator?: () => string
  /** Preserve extended props in ICS custom properties */
  preserveExtendedProps?: boolean
}
