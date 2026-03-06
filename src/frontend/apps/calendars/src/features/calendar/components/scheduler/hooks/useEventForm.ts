import { useCallback, useEffect, useRef, useState } from "react";
import type {
  IcsEvent,
  IcsAttendee,
  IcsAlarm,
  IcsRecurrenceRule,
  IcsClassType,
  IcsEventStatusType,
  IcsTimeTransparentType,
  IcsOrganizer,
} from "ts-ics";
import type { EventCalendarAdapter } from "../../../services/dav/EventCalendarAdapter";
import type { ResourcePrincipal } from "@/features/resources/api/useResourcePrincipals";
import type { AttachmentMeta, EventFormSectionId } from "../types";
import { cleanEventForDisplay } from "../utils/eventDisplayRules";
import {
  formatDateTimeLocal,
  formatDateLocal,
  parseDateTimeLocal,
  parseDateLocal,
} from "../utils/dateFormatters";

const BROWSER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

interface UseEventFormParams {
  event: Partial<IcsEvent> | null;
  calendarUrl: string;
  adapter: EventCalendarAdapter;
  organizer: IcsOrganizer | undefined;
  mode: "create" | "edit";
  availableResources?: ResourcePrincipal[];
}

export const useEventForm = ({
  event,
  calendarUrl,
  adapter,
  organizer,
  mode,
  availableResources = [],
}: UseEventFormParams) => {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [startDateTime, setStartDateTime] = useState("");
  const [endDateTime, setEndDateTime] = useState("");
  // Stash full datetime strings so toggling all-day off restores the original times
  const savedDateTimesRef = useRef({ start: "", end: "" });
  const [selectedCalendarUrl, setSelectedCalendarUrl] = useState(calendarUrl);
  const [isAllDay, setIsAllDay] = useState(false);
  const [attendees, setAttendees] = useState<IcsAttendee[]>([]);
  const [resources, setResources] = useState<ResourcePrincipal[]>([]);
  const [recurrence, setRecurrence] = useState<IcsRecurrenceRule | undefined>(
    undefined,
  );
  const [alarms, setAlarms] = useState<IcsAlarm[]>([]);
  const [videoConferenceUrl, setVideoConferenceUrl] = useState("");
  const [attachments, setAttachments] = useState<AttachmentMeta[]>([]);
  const [status, setStatus] = useState<IcsEventStatusType>("CONFIRMED");
  const [visibility, setVisibility] = useState<IcsClassType>("PUBLIC");
  const [availability, setAvailability] =
    useState<IcsTimeTransparentType>("OPAQUE");
  const [expandedSections, setExpandedSections] = useState<
    Set<EventFormSectionId>
  >(new Set());

  // Reset form when event changes
  useEffect(() => {
    setTitle(event?.summary || "");
    setSelectedCalendarUrl(calendarUrl);
    setStatus(event?.status || "CONFIRMED");
    setVisibility(event?.class || "PUBLIC");
    setAvailability(event?.timeTransparent || "OPAQUE");

    // Clean and deduplicate description / location / url for display
    const cleaned = cleanEventForDisplay({
      description: event?.description || "",
      location: event?.location || "",
      url: event?.url || "",
    });
    setDescription(cleaned.description);
    setLocation(cleaned.location);
    setVideoConferenceUrl(cleaned.url);
    setAlarms(event?.alarms || []);
    setAttachments([]);

    // Initialize attendees – split resource attendees from people
    let hasResourceAttendees = false;
    if (event?.attendees && event.attendees.length > 0) {
      const resourceEmails = new Set(
        availableResources
          .filter((r) => r.email)
          .map((r) => r.email!.toLowerCase()),
      );
      const peopleAttendees: IcsAttendee[] = [];
      const matchedResources: ResourcePrincipal[] = [];

      for (const att of event.attendees) {
        const email = att.email.toLowerCase();
        const resource = availableResources.find(
          (r) => r.email && r.email.toLowerCase() === email,
        );
        if (resource && resourceEmails.has(email)) {
          matchedResources.push(resource);
        } else {
          peopleAttendees.push(att);
        }
      }

      setAttendees(peopleAttendees);
      setResources(matchedResources);
      hasResourceAttendees = matchedResources.length > 0;
    } else {
      setAttendees([]);
      setResources([]);
    }

    // Initialize recurrence
    if (event?.recurrenceRule) {
      setRecurrence(event.recurrenceRule);
    } else {
      setRecurrence(undefined);
    }

    // Initialize all-day
    const eventIsAllDay = event?.start?.type === "DATE";
    setIsAllDay(eventIsAllDay);

    const initialExpanded = new Set<EventFormSectionId>();
    if (cleaned.location) initialExpanded.add("location");
    if (cleaned.description) initialExpanded.add("description");
    if (event?.recurrenceRule) initialExpanded.add("recurrence");
    if (cleaned.url) initialExpanded.add("videoConference");

    if (mode === "create") {
      initialExpanded.add("attendees");
    } else if (
      event?.attendees?.some(
        (att) =>
          att.email.toLowerCase() !== organizer?.email?.toLowerCase(),
      )
    ) {
      initialExpanded.add("attendees");
    }

    if (hasResourceAttendees) {
      initialExpanded.add("resources");
    }

    setExpandedSections(initialExpanded);

    // Parse start/end dates and stash full datetime strings for all-day toggle
    let initStart = "";
    let initEnd = "";

    if (event?.start?.date) {
      const startDate =
        event.start.date instanceof Date
          ? event.start.date
          : new Date(event.start.date);
      const isFakeUtc = Boolean(event.start.local?.timezone);

      if (eventIsAllDay) {
        initStart = formatDateLocal(startDate, isFakeUtc);
      } else {
        initStart = formatDateTimeLocal(startDate, isFakeUtc);
      }
    } else {
      if (eventIsAllDay) {
        initStart = formatDateLocal(new Date());
      } else {
        initStart = formatDateTimeLocal(new Date());
      }
    }

    if (event?.end?.date) {
      const endDate =
        event.end.date instanceof Date
          ? event.end.date
          : new Date(event.end.date);
      const isFakeUtc = Boolean(event.end.local?.timezone);

      if (eventIsAllDay) {
        const displayEndDate = new Date(endDate);
        displayEndDate.setUTCDate(displayEndDate.getUTCDate() - 1);
        initEnd = formatDateLocal(displayEndDate, isFakeUtc);
      } else {
        initEnd = formatDateTimeLocal(endDate, isFakeUtc);
      }
    } else {
      if (eventIsAllDay) {
        initEnd = formatDateLocal(new Date());
      } else {
        const defaultEnd = new Date();
        defaultEnd.setHours(defaultEnd.getHours() + 1);
        initEnd = formatDateTimeLocal(defaultEnd);
      }
    }

    setStartDateTime(initStart);
    setEndDateTime(initEnd);

    // For timed events, stash the full datetime so toggling all-day off
    // can restore the original times instead of defaulting to midnight.
    if (!eventIsAllDay) {
      savedDateTimesRef.current = { start: initStart, end: initEnd };
    }
  }, [event, calendarUrl, mode, organizer?.email, availableResources]);

  const toggleSection = useCallback((sectionId: EventFormSectionId) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }, []);

  const isSectionExpanded = useCallback(
    (sectionId: EventFormSectionId) => expandedSections.has(sectionId),
    [expandedSections],
  );

  const handleStartDateChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newStartValue = e.target.value;

      if (isAllDay) {
        const oldStart = parseDateLocal(startDateTime);
        const oldEnd = parseDateLocal(endDateTime);
        const duration = oldEnd.getTime() - oldStart.getTime();
        const newStart = parseDateLocal(newStartValue);
        const newEnd = new Date(newStart.getTime() + duration);
        setStartDateTime(newStartValue);
        setEndDateTime(formatDateLocal(newEnd));
      } else {
        const oldStart = parseDateTimeLocal(startDateTime);
        const oldEnd = parseDateTimeLocal(endDateTime);
        const duration = oldEnd.getTime() - oldStart.getTime();
        const newStart = parseDateTimeLocal(newStartValue);
        const newEnd = new Date(newStart.getTime() + duration);
        setStartDateTime(newStartValue);
        setEndDateTime(formatDateTimeLocal(newEnd));
      }
    },
    [isAllDay, startDateTime, endDateTime],
  );

  const handleAllDayChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newIsAllDay = e.target.checked;
      setIsAllDay(newIsAllDay);

      if (newIsAllDay) {
        // Stash current datetimes before stripping the time portion
        savedDateTimesRef.current = { start: startDateTime, end: endDateTime };
        const start = parseDateTimeLocal(startDateTime);
        const end = parseDateTimeLocal(endDateTime);
        setStartDateTime(formatDateLocal(start));
        setEndDateTime(formatDateLocal(end));
      } else {
        // Restore stashed datetimes to preserve the original time of day
        if (savedDateTimesRef.current.start) {
          setStartDateTime(savedDateTimesRef.current.start);
          setEndDateTime(savedDateTimesRef.current.end);
        } else {
          const start = parseDateLocal(startDateTime);
          const end = parseDateLocal(endDateTime);
          setStartDateTime(formatDateTimeLocal(start));
          setEndDateTime(formatDateTimeLocal(end));
        }
      }
    },
    [startDateTime, endDateTime],
  );

  const toIcsEvent = useCallback((): IcsEvent => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { duration: _duration, ...eventWithoutDuration } = event ?? {};

    // Merge resource attendees back into the attendees list
    const resourceAttendees: IcsAttendee[] = resources
      .filter((r) => r.email)
      .map((r) => {
        // Preserve partstat from the original event if available
        const existing = event?.attendees?.find(
          (a) => a.email.toLowerCase() === r.email!.toLowerCase(),
        );
        return {
          email: r.email!,
          partstat: existing?.partstat ?? "NEEDS-ACTION",
          rsvp: false,
          role: "NON-PARTICIPANT" as const,
        };
      });
    const allAttendees = [...attendees, ...resourceAttendees];


    if (isAllDay) {
      const startDate = parseDateLocal(startDateTime);
      const endDate = parseDateLocal(endDateTime);
      const utcStart = new Date(
        Date.UTC(
          startDate.getFullYear(),
          startDate.getMonth(),
          startDate.getDate(),
        ),
      );
      const utcEnd = new Date(
        Date.UTC(
          endDate.getFullYear(),
          endDate.getMonth(),
          endDate.getDate() + 1,
        ),
      );

      return {
        ...eventWithoutDuration,
        uid: event?.uid || crypto.randomUUID(),
        summary: title,
        description: description || undefined,
        location: location || undefined,
        stamp: event?.stamp || { date: new Date() },
        start: { date: utcStart, type: "DATE" },
        end: { date: utcEnd, type: "DATE" },
        organizer,
        attendees: allAttendees.length > 0 ? allAttendees : undefined,
        recurrenceRule: recurrence,
        alarms: alarms.length > 0 ? alarms : undefined,
        url: videoConferenceUrl || undefined,
        status,
        class: visibility,
        timeTransparent: availability,
      } as IcsEvent;
    }

    const startDate = parseDateTimeLocal(startDateTime);
    const endDate = parseDateTimeLocal(endDateTime);
    const fakeUtcStart = new Date(
      Date.UTC(
        startDate.getFullYear(),
        startDate.getMonth(),
        startDate.getDate(),
        startDate.getHours(),
        startDate.getMinutes(),
        startDate.getSeconds(),
      ),
    );
    const fakeUtcEnd = new Date(
      Date.UTC(
        endDate.getFullYear(),
        endDate.getMonth(),
        endDate.getDate(),
        endDate.getHours(),
        endDate.getMinutes(),
        endDate.getSeconds(),
      ),
    );

    return {
      ...eventWithoutDuration,
      uid: event?.uid || crypto.randomUUID(),
      summary: title,
      description: description || undefined,
      location: location || undefined,
      stamp: event?.stamp || { date: new Date() },
      start: {
        date: fakeUtcStart,
        type: "DATE-TIME",
        local: {
          date: fakeUtcStart,
          timezone: BROWSER_TIMEZONE,
          tzoffset: adapter.getTimezoneOffset(startDate, BROWSER_TIMEZONE),
        },
      },
      end: {
        date: fakeUtcEnd,
        type: "DATE-TIME",
        local: {
          date: fakeUtcEnd,
          timezone: BROWSER_TIMEZONE,
          tzoffset: adapter.getTimezoneOffset(endDate, BROWSER_TIMEZONE),
        },
      },
      organizer,
      attendees: allAttendees.length > 0 ? allAttendees : undefined,
      recurrenceRule: recurrence,
      alarms: alarms.length > 0 ? alarms : undefined,
      url: videoConferenceUrl || undefined,
      status,
      class: visibility,
      timeTransparent: availability,
    } as IcsEvent;
  }, [
    event,
    isAllDay,
    startDateTime,
    endDateTime,
    title,
    description,
    location,
    organizer,
    attendees,
    resources,
    recurrence,
    alarms,
    videoConferenceUrl,
    status,
    visibility,
    availability,
    adapter,
  ]);

  return {
    // Basic fields
    title,
    setTitle,
    description,
    setDescription,
    location,
    setLocation,
    startDateTime,
    endDateTime,
    setEndDateTime,
    selectedCalendarUrl,
    setSelectedCalendarUrl,
    isAllDay,

    // Complex fields
    attendees,
    setAttendees,
    resources,
    setResources,
    recurrence,
    setRecurrence,
    alarms,
    setAlarms,
    videoConferenceUrl,
    setVideoConferenceUrl,
    attachments,
    setAttachments,
    status,
    setStatus,
    visibility,
    setVisibility,
    availability,
    setAvailability,

    // Section management
    toggleSection,
    isSectionExpanded,

    // Handlers
    handleStartDateChange,
    handleAllDayChange,

    // Conversion
    toIcsEvent,
  };
};
