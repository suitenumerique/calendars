/**
 * EventModal component.
 * Handles creation and editing of calendar events.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  IcsEvent,
  IcsAttendee,
  IcsOrganizer,
  IcsRecurrenceRule,
} from "ts-ics";
import {
  Button,
  Input,
  Modal,
  ModalSize,
  Select,
  TextArea,
} from "@gouvfr-lasuite/cunningham-react";

import { useAuth } from "@/features/auth/Auth";
import { AttendeesInput } from "../AttendeesInput";
import { RecurrenceEditor } from "../RecurrenceEditor";
import { DeleteEventModal } from "./DeleteEventModal";
import type { EventModalProps, RecurringDeleteOption } from "./types";
import {
  formatDateTimeLocal,
  formatDateLocal,
  parseDateTimeLocal,
  parseDateLocal,
} from "./utils/dateFormatters";

// Get browser timezone
const BROWSER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

export const EventModal = ({
  isOpen,
  mode,
  event,
  calendarUrl,
  calendars,
  adapter,
  onSave,
  onDelete,
  onRespondToInvitation,
  onClose,
}: EventModalProps) => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [title, setTitle] = useState(event?.summary || "");
  const [description, setDescription] = useState(event?.description || "");
  const [location, setLocation] = useState(event?.location || "");
  const [startDateTime, setStartDateTime] = useState("");
  const [endDateTime, setEndDateTime] = useState("");
  const [selectedCalendarUrl, setSelectedCalendarUrl] = useState(calendarUrl);
  const [isLoading, setIsLoading] = useState(false);
  const [attendees, setAttendees] = useState<IcsAttendee[]>([]);
  const [showAttendees, setShowAttendees] = useState(false);
  const [recurrence, setRecurrence] = useState<IcsRecurrenceRule | undefined>(
    event?.recurrenceRule
  );
  const [showRecurrence, setShowRecurrence] = useState(() => {
    return !!event?.recurrenceRule;
  });
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [isAllDay, setIsAllDay] = useState(() => {
    return event?.start?.type === 'DATE';
  });

  // Calculate organizer
  const organizer: IcsOrganizer | undefined =
    event?.organizer ||
    (user?.email
      ? { email: user.email, name: user.email.split('@')[0] }
      : undefined);

  // Check if current user is an attendee (invited to this event)
  const currentUserAttendee = event?.attendees?.find(
    (att) => user?.email && att.email.toLowerCase() === user.email.toLowerCase()
  );
  const isInvited = !!(
    event?.organizer &&
    currentUserAttendee &&
    event.organizer.email !== user?.email
  );
  const currentParticipationStatus =
    currentUserAttendee?.partstat || 'NEEDS-ACTION';

  // Reset form when event changes
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

    // Initialize recurrence from event
    if (event?.recurrenceRule) {
      setRecurrence(event.recurrenceRule);
      setShowRecurrence(true);
    } else {
      setRecurrence(undefined);
      setShowRecurrence(false);
    }

    // Initialize all-day from event
    const eventIsAllDay = event?.start?.type === 'DATE';
    setIsAllDay(eventIsAllDay);

    // Parse start/end dates
    // Dates from adapter have timezone info and are "fake UTC" - use getUTC* methods
    if (event?.start?.date) {
      const startDate =
        event.start.date instanceof Date
          ? event.start.date
          : new Date(event.start.date);
      // If there's timezone info, the date is "fake UTC"
      const isFakeUtc = Boolean(event.start.local?.timezone);

      if (eventIsAllDay) {
        setStartDateTime(formatDateLocal(startDate, isFakeUtc));
      } else {
        setStartDateTime(formatDateTimeLocal(startDate, isFakeUtc));
      }
    } else {
      if (eventIsAllDay) {
        setStartDateTime(formatDateLocal(new Date()));
      } else {
        setStartDateTime(formatDateTimeLocal(new Date()));
      }
    }

    if (event?.end?.date) {
      const endDate =
        event.end.date instanceof Date
          ? event.end.date
          : new Date(event.end.date);
      const isFakeUtc = Boolean(event.end.local?.timezone);

      if (eventIsAllDay) {
        // For all-day events, the end date in ICS is exclusive (next day)
        // But in the UI we want to show the inclusive end date (same day for 1-day event)
        // So subtract 1 day when displaying
        const displayEndDate = new Date(endDate);
        displayEndDate.setUTCDate(displayEndDate.getUTCDate() - 1);
        setEndDateTime(formatDateLocal(displayEndDate, isFakeUtc));
      } else {
        setEndDateTime(formatDateTimeLocal(endDate, isFakeUtc));
      }
    } else {
      if (eventIsAllDay) {
        // Default: same day
        setEndDateTime(formatDateLocal(new Date()));
      } else {
        // Default: 1 hour after start
        const defaultEnd = new Date();
        defaultEnd.setHours(defaultEnd.getHours() + 1);
        setEndDateTime(formatDateTimeLocal(defaultEnd));
      }
    }
  }, [event, calendarUrl]);

  const handleSave = async () => {
    setIsLoading(true);
    try {
      // Remove duration to avoid union type conflict
      // (IcsEvent is either end or duration, not both)
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { duration: _duration, ...eventWithoutDuration } = event ?? {};

      let icsEvent: IcsEvent;

      if (isAllDay) {
        // All-day event
        const startDate = parseDateLocal(startDateTime);
        const endDate = parseDateLocal(endDateTime);

        // Create UTC dates for all-day events
        const utcStart = new Date(
          Date.UTC(
            startDate.getFullYear(),
            startDate.getMonth(),
            startDate.getDate()
          )
        );
        // For all-day events, the end date in ICS is exclusive (next day)
        // The user enters the inclusive end date, so we add 1 day for ICS
        const utcEnd = new Date(
          Date.UTC(
            endDate.getFullYear(),
            endDate.getMonth(),
            endDate.getDate() + 1 // Add 1 day for exclusive end
          )
        );

        icsEvent = {
          ...eventWithoutDuration,
          uid: event?.uid || crypto.randomUUID(),
          summary: title,
          description: description || undefined,
          location: location || undefined,
          stamp: event?.stamp || { date: new Date() },
          start: {
            date: utcStart,
            type: "DATE",
          },
          end: {
            date: utcEnd,
            type: "DATE",
          },
          organizer: organizer,
          attendees: attendees.length > 0 ? attendees : undefined,
          recurrenceRule: recurrence,
        };
      } else {
        // Timed event
        const startDate = parseDateTimeLocal(startDateTime);
        const endDate = parseDateTimeLocal(endDateTime);

        // Create "fake UTC" dates where getUTCHours() = local hours
        // This is required because ts-ics uses getUTCHours() to generate ICS
        const fakeUtcStart = new Date(
          Date.UTC(
            startDate.getFullYear(),
            startDate.getMonth(),
            startDate.getDate(),
            startDate.getHours(),
            startDate.getMinutes(),
            startDate.getSeconds()
          )
        );
        const fakeUtcEnd = new Date(
          Date.UTC(
            endDate.getFullYear(),
            endDate.getMonth(),
            endDate.getDate(),
            endDate.getHours(),
            endDate.getMinutes(),
            endDate.getSeconds()
          )
        );

        icsEvent = {
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
          organizer: organizer,
          attendees: attendees.length > 0 ? attendees : undefined,
          recurrenceRule: recurrence,
        };
      }

      await onSave(icsEvent, selectedCalendarUrl);
      onClose();
    } catch (error) {
      console.error("Failed to save event:", error);
      alert(t('api.error.unexpected'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteClick = () => {
    setShowDeleteModal(true);
  };

  const handleDeleteConfirm = async (option?: RecurringDeleteOption) => {
    if (!onDelete || !event?.uid) return;

    setShowDeleteModal(false);
    setIsLoading(true);
    try {
      await onDelete(event as IcsEvent, selectedCalendarUrl, option);
      onClose();
    } catch (error) {
      console.error("Failed to delete event:", error);
      alert(t('api.error.unexpected'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteCancel = () => {
    setShowDeleteModal(false);
  };

  const handleRespondToInvitation = async (
    status: 'ACCEPTED' | 'TENTATIVE' | 'DECLINED'
  ) => {
    if (!onRespondToInvitation || !event) return;

    setIsLoading(true);
    try {
      await onRespondToInvitation(event as IcsEvent, status);
      // Update local state to reflect new status
      setAttendees((prev) =>
        prev.map((att) =>
          user?.email && att.email.toLowerCase() === user.email.toLowerCase()
            ? { ...att, partstat: status }
            : att
        )
      );
    } catch (error) {
      console.error("Failed to respond to invitation:", error);
      alert(t('api.error.unexpected'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleStartDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
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
  };

  const handleAllDayChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newIsAllDay = e.target.checked;
    setIsAllDay(newIsAllDay);

    // Convert dates when switching modes
    if (newIsAllDay) {
      // Convert to date-only format
      const start = parseDateTimeLocal(startDateTime);
      const end = parseDateTimeLocal(endDateTime);
      setStartDateTime(formatDateLocal(start));
      setEndDateTime(formatDateLocal(end));
    } else {
      // Convert to datetime format
      const start = parseDateLocal(startDateTime);
      const end = parseDateLocal(endDateTime);
      setStartDateTime(formatDateTimeLocal(start));
      setEndDateTime(formatDateTimeLocal(end));
    }
  };

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={ModalSize.MEDIUM}
        title={
          mode === "create"
            ? t('calendar.event.createTitle')
            : t('calendar.event.editTitle')
        }
        leftActions={
          mode === "edit" && onDelete ? (
            <Button
              color="error"
              onClick={handleDeleteClick}
              disabled={isLoading}
            >
              {t('calendar.event.delete')}
            </Button>
          ) : undefined
        }
        rightActions={
          <>
            <Button color="neutral" onClick={onClose} disabled={isLoading}>
              {t('calendar.event.cancel')}
            </Button>
            <Button
              color="brand"
              onClick={handleSave}
              disabled={isLoading || !title.trim()}
            >
              {isLoading ? "..." : t('calendar.event.save')}
            </Button>
          </>
        }
      >
        <div className="event-modal__content">
          <Input
            label={t('calendar.event.title')}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            fullWidth
          />

          {/* Invitation Response Section */}
          {isInvited && mode === 'edit' && onRespondToInvitation && (
            <div className="event-modal__invitation">
              <div className="event-modal__invitation-header">
                <span className="event-modal__invitation-label">
                  {t('calendar.event.invitation', { defaultValue: 'Invitation' })}
                </span>
                <span className="event-modal__invitation-organizer">
                  {t('calendar.event.organizedBy', {
                    defaultValue: 'Organisé par',
                  })}{' '}
                  {event?.organizer?.name || event?.organizer?.email}
                </span>
              </div>
              <div className="event-modal__invitation-actions">
                <Button
                  size="small"
                  color={
                    currentParticipationStatus === 'ACCEPTED'
                      ? 'success'
                      : 'neutral'
                  }
                  onClick={() => handleRespondToInvitation('ACCEPTED')}
                  disabled={
                    isLoading || currentParticipationStatus === 'ACCEPTED'
                  }
                >
                  ✓ {t('calendar.event.accept', { defaultValue: 'Accepter' })}
                </Button>
                <Button
                  size="small"
                  color={
                    currentParticipationStatus === 'TENTATIVE'
                      ? 'warning'
                      : 'neutral'
                  }
                  onClick={() => handleRespondToInvitation('TENTATIVE')}
                  disabled={
                    isLoading || currentParticipationStatus === 'TENTATIVE'
                  }
                >
                  ? {t('calendar.event.maybe', { defaultValue: 'Peut-être' })}
                </Button>
                <Button
                  size="small"
                  color={
                    currentParticipationStatus === 'DECLINED'
                      ? 'error'
                      : 'neutral'
                  }
                  onClick={() => handleRespondToInvitation('DECLINED')}
                  disabled={
                    isLoading || currentParticipationStatus === 'DECLINED'
                  }
                >
                  ✗ {t('calendar.event.decline', { defaultValue: 'Refuser' })}
                </Button>
              </div>
              {currentParticipationStatus && (
                <div className="event-modal__invitation-status">
                  {t('calendar.event.yourResponse', {
                    defaultValue: 'Votre réponse',
                  })}
                  :{' '}
                  <strong>
                    {currentParticipationStatus === 'ACCEPTED' &&
                      t('calendar.event.accepted', { defaultValue: 'Accepté' })}
                    {currentParticipationStatus === 'TENTATIVE' &&
                      t('calendar.event.tentative', {
                        defaultValue: 'Peut-être',
                      })}
                    {currentParticipationStatus === 'DECLINED' &&
                      t('calendar.event.declined', { defaultValue: 'Refusé' })}
                    {currentParticipationStatus === 'NEEDS-ACTION' &&
                      t('calendar.event.needsAction', {
                        defaultValue: 'En attente',
                      })}
                  </strong>
                </div>
              )}
            </div>
          )}

          <Select
            label={t('calendar.event.calendar', { defaultValue: 'Calendrier' })}
            value={selectedCalendarUrl}
            onChange={(e) => setSelectedCalendarUrl(String(e.target.value))}
            options={calendars.map((cal) => ({
              value: cal.url,
              label: cal.displayName || cal.url,
            }))}
            fullWidth
          />

          <label className="event-modal__checkbox">
            <input
              type="checkbox"
              checked={isAllDay}
              onChange={handleAllDayChange}
            />
            <span>{t('calendar.event.allDay')}</span>
          </label>

          <div className="event-modal__datetime-row">
            <Input
              type={isAllDay ? "date" : "datetime-local"}
              label={t('calendar.event.start')}
              value={startDateTime}
              onChange={handleStartDateChange}
              fullWidth
            />
            <Input
              type={isAllDay ? "date" : "datetime-local"}
              label={t('calendar.event.end')}
              value={endDateTime}
              onChange={(e) => setEndDateTime(e.target.value)}
              fullWidth
            />
          </div>

          <Input
            label={t('calendar.event.location')}
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            fullWidth
          />

          <TextArea
            label={t('calendar.event.description')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            fullWidth
          />

          <div className="event-modal__features">
            <button
              type="button"
              className={`event-modal__feature-tag ${
                showAttendees ? 'event-modal__feature-tag--active' : ''
              }`}
              onClick={() => setShowAttendees(!showAttendees)}
            >
              <span className="material-icons">people</span>
              {t('calendar.event.attendees')}
              {attendees.length > 0 && ` (${attendees.length})`}
            </button>

            <button
              type="button"
              className={`event-modal__feature-tag ${
                showRecurrence ? 'event-modal__feature-tag--active' : ''
              }`}
              onClick={() => setShowRecurrence(!showRecurrence)}
            >
              <span className="material-icons">repeat</span>
              {t('calendar.recurrence.label')}
            </button>
          </div>

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

          {showRecurrence && (
            <div className="event-modal__recurrence-editor">
              <RecurrenceEditor value={recurrence} onChange={setRecurrence} />
            </div>
          )}
        </div>
      </Modal>

      <DeleteEventModal
        isOpen={showDeleteModal}
        isRecurring={!!recurrence}
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
      />
    </>
  );
};
