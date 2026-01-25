import { useState, useCallback, type KeyboardEvent } from 'react';
import { Input } from '@gouvfr-lasuite/cunningham-react';
import { useTranslation } from 'react-i18next';
import type { IcsAttendee, IcsOrganizer } from 'ts-ics';

interface AttendeesInputProps {
  attendees: IcsAttendee[];
  onChange: (attendees: IcsAttendee[]) => void;
  organizerEmail?: string;
  organizer?: IcsOrganizer;
}

// Validate email format
const isValidEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

// Get partstat display style
const getPartstatStyle = (partstat?: string): { bgColor: string; textColor: string } => {
  switch (partstat) {
    case 'ACCEPTED':
      return { bgColor: '#d4edda', textColor: '#155724' };
    case 'DECLINED':
      return { bgColor: '#f8d7da', textColor: '#721c24' };
    case 'TENTATIVE':
      return { bgColor: '#fff3cd', textColor: '#856404' };
    default: // NEEDS-ACTION or undefined
      return { bgColor: '#e9ecef', textColor: '#495057' };
  }
};

// Get partstat icon
const getPartstatIcon = (partstat?: string): string => {
  switch (partstat) {
    case 'ACCEPTED':
      return 'check_circle';
    case 'DECLINED':
      return 'cancel';
    case 'TENTATIVE':
      return 'help';
    default:
      return 'schedule';
  }
};

export function AttendeesInput({ attendees, onChange, organizerEmail, organizer }: AttendeesInputProps) {
  const { t } = useTranslation();
  const [inputValue, setInputValue] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Calculate total participants (organizer + attendees)
  const totalParticipants = (organizer ? 1 : 0) + attendees.length;

  const addAttendee = useCallback(() => {
    const email = inputValue.trim().toLowerCase();

    if (!email) {
      return;
    }

    if (!isValidEmail(email)) {
      setError(t('calendar.attendees.invalidEmail'));
      return;
    }

    // Check if already in list
    if (attendees.some(a => a.email.toLowerCase() === email)) {
      setError(t('calendar.attendees.alreadyAdded'));
      return;
    }

    // Check if it's the organizer
    if (organizerEmail && email === organizerEmail.toLowerCase()) {
      setError(t('calendar.attendees.cannotAddOrganizer'));
      return;
    }

    const newAttendee: IcsAttendee = {
      email,
      partstat: 'NEEDS-ACTION',
      rsvp: true,
      role: 'REQ-PARTICIPANT',
    };

    onChange([...attendees, newAttendee]);
    setInputValue('');
    setError(null);
  }, [inputValue, attendees, onChange, organizerEmail, t]);

  const removeAttendee = useCallback((emailToRemove: string) => {
    onChange(attendees.filter(a => a.email !== emailToRemove));
  }, [attendees, onChange]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addAttendee();
    }
  }, [addAttendee]);

  return (
    <div className="attendees-input">
      <div className="attendees-input__field">
        <Input
          label={t('calendar.attendees.label')}
          fullWidth
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={handleKeyDown}
          state={error ? 'error' : 'default'}
          text={error || undefined}
          icon={<span className="material-icons">person_add</span>}
        />
      </div>

      {totalParticipants > 0 && (
        <div className="attendees-input__participants">
          <div className="attendees-input__header">
            <h3 className="attendees-input__title">
              {t('calendar.attendees.participants')}
              <span className="attendees-input__badge">{totalParticipants}</span>
            </h3>
          </div>

          <div className="attendees-input__list">
            {/* Organizer */}
            {organizer && (
              <div className="attendees-input__item">
                <span className="material-icons attendees-input__status-icon attendees-input__status-icon--accepted">
                  check_circle
                </span>
                <div className="attendees-input__item-content">
                  <span className="attendees-input__item-name">
                    {organizer.name || organizer.email}
                  </span>
                  <span className="attendees-input__organizer-badge">
                    {t('calendar.attendees.organizer')}
                  </span>
                </div>
                <button
                  type="button"
                  className="attendees-input__action-btn"
                  aria-label={t('calendar.attendees.viewProfile')}
                >
                  <span className="material-icons">person</span>
                </button>
                <button
                  type="button"
                  className="attendees-input__action-btn attendees-input__action-btn--remove"
                  disabled
                  aria-label={t('calendar.attendees.cannotRemoveOrganizer')}
                >
                  <span className="material-icons">close</span>
                </button>
              </div>
            )}

            {/* Attendees */}
            {attendees.map((attendee) => {
              const icon = getPartstatIcon(attendee.partstat);
              const isAccepted = attendee.partstat === 'ACCEPTED';

              return (
                <div key={attendee.email} className="attendees-input__item">
                  <span
                    className={`material-icons attendees-input__status-icon ${
                      isAccepted
                        ? 'attendees-input__status-icon--accepted'
                        : 'attendees-input__status-icon--pending'
                    }`}
                  >
                    {icon}
                  </span>
                  <div className="attendees-input__item-content">
                    <span className="attendees-input__item-name">
                      {attendee.name || attendee.email}
                    </span>
                    {attendee.name && (
                      <span className="attendees-input__item-email">
                        &lt;{attendee.email}&gt;
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="attendees-input__action-btn"
                    aria-label={t('calendar.attendees.viewProfile')}
                  >
                    <span className="material-icons">person</span>
                  </button>
                  <button
                    type="button"
                    className="attendees-input__action-btn attendees-input__action-btn--remove"
                    onClick={() => removeAttendee(attendee.email)}
                    aria-label={t('calendar.attendees.remove')}
                  >
                    <span className="material-icons">close</span>
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
