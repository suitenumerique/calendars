import { Modal, Button, Input, TextArea, Select } from '@openfun/cunningham-react';
import type { IcsEvent, IcsRecurrenceRule } from 'ts-ics';
import { useState, useEffect, useRef } from "react";
import { RecurrenceEditor } from './RecurrenceEditor';

// Helper function to check if event is all-day (same logic as open-dav-calendar)
function isEventAllDay(event: IcsEvent): boolean {
  return event.start.type === 'DATE' || (event.end?.type === 'DATE');
}

// Calendar type from open-calendar (exported for use in other components)
export interface Calendar {
  url: string;
  uid?: unknown;
  displayName?: string;
  calendarColor?: string;
  description?: string;
}

interface EventModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  calendars: Calendar[];
  selectedEvent?: IcsEvent | null;
  calendarUrl: string;
  onSubmit: (event: IcsEvent, calendarUrl: string) => Promise<void>;
  onAllDayChange: (isAllDay: boolean) => void;
  onClose: () => void;
  onDelete?: (event: IcsEvent, calendarUrl: string) => Promise<void>;
}

const VISIBILITY_OPTIONS = [
  { value: 'default', label: 'Par défaut' },
  { value: 'public', label: 'Public' },
  { value: 'private', label: 'Privé' },
] as const;

export function EventModal({
  isOpen,
  mode,
  calendars,
  selectedEvent,
  calendarUrl,
  onSubmit,
  onAllDayChange,
  onClose,
  onDelete,
}: EventModalProps) {
  const titleInputRef = useRef<HTMLInputElement>(null);
  const [formData, setFormData] = useState<Partial<IcsEvent & { startTime?: string; endTime?: string }>>({});
  const [activeFeatures, setActiveFeatures] = useState<Set<string>>(new Set());
  const [selectedCalendarUrl, setSelectedCalendarUrl] = useState<string>(calendarUrl);
  const [allDay, setAllDay] = useState<boolean>(false);

  // Helper to get local date from IcsDateObject
  const getLocalDate = (dateObj: { date: Date; local?: { date: Date; timezone: string } }): Date => {
    return dateObj.local?.date || dateObj.date;
  };

  // Format date for input
  const formatDateForInput = (date: Date): string => {
    return date.toISOString().split('T')[0];
  };

  // Format time for input
  const formatTimeForInput = (date: Date): string => {
    return date.toTimeString().slice(0, 5);
  };

  useEffect(() => {
    if (selectedEvent) {
      const eventAllDay = isEventAllDay(selectedEvent);
      const startDate = getLocalDate(selectedEvent.start);
      const endDate = selectedEvent.end ? getLocalDate(selectedEvent.end) : startDate;
      
      setAllDay(eventAllDay);
      setFormData({
        ...selectedEvent,
        summary: selectedEvent.summary || '',
        startTime: eventAllDay ? undefined : formatTimeForInput(startDate),
        endTime: eventAllDay ? undefined : formatTimeForInput(endDate),
      });
      setSelectedCalendarUrl(calendarUrl);
    } else {
      const now = new Date();
      const endTime = new Date(now.getTime() + 30 * 60 * 1000);
      setAllDay(false);
      setFormData({
        summary: '',
        start: {
          type: 'DATE-TIME',
          date: now,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
        end: {
          type: 'DATE-TIME',
          date: endTime,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
        startTime: formatTimeForInput(now),
        endTime: formatTimeForInput(endTime),
      });
      setSelectedCalendarUrl(calendars[0]?.url || '');
    }
  }, [selectedEvent, calendars, calendarUrl]);

  useEffect(() => {
    if (isOpen) {
      requestAnimationFrame(() => {
        titleInputRef.current?.focus();
      });
    }
  }, [isOpen]);

  const startDate = formData.start ? getLocalDate(formData.start) : new Date();
  const endDate = formData.end ? getLocalDate(formData.end) : startDate;

  const toggleFeature = (feature: string) => {
    if (feature === 'allDay') {
      const newAllDay = !allDay;
      setAllDay(newAllDay);
      onAllDayChange(newAllDay);
      return;
    }

    setActiveFeatures(prev => {
      const next = new Set(prev);
      if (next.has(feature)) {
        next.delete(feature);
      } else {
        next.add(feature);
      }
      return next;
    });
  };

  const handleSubmit = async () => {
    if (!formData.summary) return;

    const startDateValue = new Date(`${formatDateForInput(startDate)}T${allDay ? '00:00:00' : formData.startTime || '00:00:00'}`);
    const endDateValue = new Date(`${formatDateForInput(endDate)}T${allDay ? '00:00:00' : formData.endTime || '00:00:00'}`);

    const updatedEvent: IcsEvent = {
      ...(selectedEvent || {}),
      uid: selectedEvent?.uid || `event-${Date.now()}`,
      summary: formData.summary || '',
      location: formData.location || undefined,
      description: formData.description || formData.notes || undefined,
      start: {
        type: allDay ? 'DATE' : 'DATE-TIME',
        date: startDateValue,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      },
      end: {
        type: allDay ? 'DATE' : 'DATE-TIME',
        date: endDateValue,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      },
      recurrenceRule: formData.recurrenceRule,
    };

    await onSubmit(updatedEvent, selectedCalendarUrl);
  };

  const renderFeatureContent = () => {
    return (
      <>
        {activeFeatures.has('calendar') && (
          <div className="event-modal-layout event-modal-layout--margin-bottom-1rem">
            <Select
              label="Calendrier"
              name="calendar-select"
              value={selectedCalendarUrl}
              onChange={(e) => setSelectedCalendarUrl(e.target.value)}
              options={calendars.map(cal => ({ 
                value: cal.url, 
                label: cal.displayName || cal.url 
              }))}
              required
            />
          </div>
        )}

        {activeFeatures.has('repeat') && (
          <div className="event-modal-layout event-modal-layout--margin-bottom-1rem">
            <RecurrenceEditor
              value={formData.recurrenceRule}
              onChange={(recurrenceRule) => {
                setFormData(prev => ({ ...prev, recurrenceRule }));
              }}
            />
          </div>
        )}

        {activeFeatures.has('location') && (
          <div className="event-modal-layout event-modal-layout--margin-bottom-1rem">
            <Input
              label="Lieu"
              placeholder="Ajouter un lieu"
              value={formData.location || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, location: e.target.value }))}
              icon={<span className="material-icons">location_on</span>}
            />
          </div>
        )}

        {activeFeatures.has('notes') && (
          <div className="event-modal-layout event-modal-layout--margin-bottom-1rem">
            <TextArea
              label="Notes"
              placeholder="Ajouter des notes"
              value={formData.description || formData.notes || ''}
              onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value, notes: e.target.value }))}
              rows={4}
            />
          </div>
        )}
      </>
    );
  };

  const selectedCalendar = calendars.find(cal => cal.url === selectedCalendarUrl);

  return (
    <Modal 
      isOpen={isOpen} 
      onClose={onClose}
      title={mode === 'create' ? 'Créer un événement' : 'Modifier l\'événement'}
    >
      <div className="event-modal-layout event-modal-layout--gap-2rem">
        <Input
          label="Titre"
          value={formData.summary || ''}
          onChange={(e) => setFormData(prev => ({ ...prev, summary: e.target.value }))}
          ref={titleInputRef}
        />

        <div className="event-modal-layout event-modal-layout--row event-modal-layout--gap-1rem">
          <div className="event-modal-layout event-modal-layout--flex-1">
            <Input
              type="date"
              label="Date de début"
              name="event-start-date"
              value={formatDateForInput(startDate)}
              onChange={(e) => {
                const newDate = new Date(e.target.value);
                const currentTime = allDay ? '00:00:00' : (formData.startTime || formatTimeForInput(startDate));
                const [hours, minutes] = currentTime.split(':');
                newDate.setHours(parseInt(hours || '0'), parseInt(minutes || '0'));
                setFormData(prev => ({
                  ...prev,
                  start: {
                    type: allDay ? 'DATE' : 'DATE-TIME',
                    date: newDate,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                  },
                  startTime: allDay ? undefined : currentTime,
                }));
              }}
              required
            />
          </div>
          {!allDay && (
            <div className="event-modal-layout event-modal-layout--flex-1">
              <Input
                type="time"
                label="Heure de début"
                name="event-start-time"
                value={formData.startTime || formatTimeForInput(startDate)}
                onChange={(e) => {
                  const [hours, minutes] = e.target.value.split(':');
                  const newDate = new Date(startDate);
                  newDate.setHours(parseInt(hours || '0'), parseInt(minutes || '0'));
                  setFormData(prev => ({
                    ...prev,
                    start: {
                      type: 'DATE-TIME',
                      date: newDate,
                      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    },
                    startTime: e.target.value,
                  }));
                }}
                required
              />
            </div>
          )}
        </div>

        <div className="event-modal-layout event-modal-layout--row event-modal-layout--gap-1rem">
          <div className="event-modal-layout event-modal-layout--flex-1">
            <Input
              type="date"
              label="Date de fin"
              name="event-end-date"
              value={formatDateForInput(endDate)}
              onChange={(e) => {
                const newDate = new Date(e.target.value);
                const currentTime = allDay ? '00:00:00' : (formData.endTime || formatTimeForInput(endDate));
                const [hours, minutes] = currentTime.split(':');
                newDate.setHours(parseInt(hours || '0'), parseInt(minutes || '0'));
                setFormData(prev => ({
                  ...prev,
                  end: {
                    type: allDay ? 'DATE' : 'DATE-TIME',
                    date: newDate,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                  },
                  endTime: allDay ? undefined : currentTime,
                }));
              }}
              required
            />
          </div>
          {!allDay && (
            <div className="event-modal-layout event-modal-layout--flex-1">
              <Input
                type="time"
                label="Heure de fin"
                name="event-end-time"
                value={formData.endTime || formatTimeForInput(endDate)}
                onChange={(e) => {
                  const [hours, minutes] = e.target.value.split(':');
                  const newDate = new Date(endDate);
                  newDate.setHours(parseInt(hours || '0'), parseInt(minutes || '0'));
                  setFormData(prev => ({
                    ...prev,
                    end: {
                      type: 'DATE-TIME',
                      date: newDate,
                      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    },
                    endTime: e.target.value,
                  }));
                }}
                required
              />
            </div>
          )}
        </div>

        {renderFeatureContent()}

        <div className="event-modal-layout event-modal-layout--row event-modal-layout--gap-0-5rem event-modal-layout--wrap">
          <button
            className={`event-modal__feature-tag ${activeFeatures.has('calendar') ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('calendar')}
            style={selectedCalendar?.calendarColor ? { 
              backgroundColor: selectedCalendar.calendarColor,
              color: 'white',
            } : undefined}
          >
            <span className="material-icons">event_note</span>
            {selectedCalendar?.displayName || selectedCalendar?.url || 'Calendrier'}
          </button>
          <button
            className={`event-modal__feature-tag ${activeFeatures.has('visibility') ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('visibility')}
          >
            <span className="material-icons">visibility</span>
            Visibilité
          </button>
          <button
            className={`event-modal__feature-tag ${activeFeatures.has('repeat') ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('repeat')}
          >
            <span className="material-icons">repeat</span>
            Répéter
          </button>
          <button
            className={`event-modal__feature-tag ${allDay ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('allDay')}
          >
            <span className="material-icons">today</span>
            Toute la journée
          </button>
          <button
            className={`event-modal__feature-tag ${activeFeatures.has('invites') ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('invites')}
          >
            <span className="material-icons">people</span>
            Invités
          </button>
          <button
            className={`event-modal__feature-tag ${activeFeatures.has('location') ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('location')}
          >
            <span className="material-icons">location_on</span>
            Lieu
          </button>
          <button
            className={`event-modal__feature-tag ${activeFeatures.has('visio') ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('visio')}
          >
            <span className="material-icons">videocam</span>
            Visio
          </button>
          <button
            className={`event-modal__feature-tag ${activeFeatures.has('notification') ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('notification')}
          >
            <span className="material-icons">notifications</span>
            Rappel
          </button>
          <button
            className={`event-modal__feature-tag ${activeFeatures.has('notes') ? 'event-modal__feature-tag--active' : ''}`}
            onClick={() => toggleFeature('notes')}
          >
            <span className="material-icons">notes</span>
            Notes
          </button>
        </div>

        <div className="event-modal-layout event-modal-layout--row event-modal-layout--justify-space-between event-modal-layout--margin-top-2rem">
          {mode === 'edit' && selectedEvent && (
            <Button
              type="button"
              color="danger"
              onClick={() => onDelete?.(selectedEvent, selectedCalendarUrl)}
              icon={<span className="material-icons">delete</span>}
            >
              Supprimer
            </Button>
          )}
          <div className="event-modal-layout event-modal-layout--row event-modal-layout--gap-1rem event-modal-layout--margin-left-auto">
            <Button
              type="button"
              color="secondary"
              onClick={onClose}
            >
              Annuler
            </Button>
            <Button onClick={handleSubmit}>
              {mode === 'create' ? 'Créer' : 'Enregistrer'}
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
