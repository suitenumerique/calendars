import { Select, Input } from '@openfun/cunningham-react';
import { useState } from 'react';
import type { IcsRecurrenceRule } from 'ts-ics';

const WEEKDAYS = [
  { value: 'MO', label: 'L' },
  { value: 'TU', label: 'M' },
  { value: 'WE', label: 'M' },
  { value: 'TH', label: 'J' },
  { value: 'FR', label: 'V' },
  { value: 'SA', label: 'S' },
  { value: 'SU', label: 'D' },
] as const;

const RECURRENCE_OPTIONS = [
  { value: 'NONE', label: 'Non' },
  { value: 'DAILY', label: 'Tous les jours' },
  { value: 'WEEKLY', label: 'Toutes les semaines' },
  { value: 'MONTHLY', label: 'Tous les mois' },
  { value: 'YEARLY', label: 'Tous les ans' },
  { value: 'CUSTOM', label: 'Personnalisé...' },
] as const;

interface RecurrenceEditorProps {
  value?: IcsRecurrenceRule;
  onChange: (rule: IcsRecurrenceRule | undefined) => void;
}

export function RecurrenceEditor({ value, onChange }: RecurrenceEditorProps) {
  const [isCustom, setIsCustom] = useState(() => {
    if (!value) return false;
    return value.interval !== 1 || value.byDay?.length || value.count || value.until;
  });

  const getSimpleValue = () => {
    if (!value) return 'NONE';
    if (isCustom) return 'CUSTOM';
    return value.freq;
  };

  const handleSimpleChange = (newValue: string) => {
    if (newValue === 'NONE') {
      setIsCustom(false);
      onChange(undefined);
      return;
    }
    
    if (newValue === 'CUSTOM') {
      setIsCustom(true);
      onChange({
        freq: 'WEEKLY',
        interval: 1
      });
      return;
    }
    
    setIsCustom(false);
    onChange({
      freq: newValue as IcsRecurrenceRule['freq'],
      interval: 1,
      byDay: undefined,
      count: undefined,
      until: undefined
    });
  };

  const handleChange = (updates: Partial<IcsRecurrenceRule>) => {
    onChange({
      freq: 'WEEKLY',
      interval: 1,
      ...value,
      ...updates
    });
  };

  return (
    <div className="recurrence-editor-layout recurrence-editor-layout--gap-1rem">
      <Select
        label="Répéter"
        value={getSimpleValue()}
        options={RECURRENCE_OPTIONS}
        onChange={(e) => handleSimpleChange(e.target.value)}
      />

      {isCustom && (
        <div className="recurrence-editor-layout recurrence-editor-layout--gap-1rem recurrence-editor-layout--margin-left-2rem">
          <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-1rem">
            <span>Répéter tous les</span>
            <Input
              type="number"
              min={1}
              value={value?.interval || 1}
              onChange={(e) => handleChange({ interval: parseInt(e.target.value) })}
              style={{ width: '80px' }}
            />
            <Select
              value={value?.freq || 'WEEKLY'}
              options={[
                { value: 'DAILY', label: 'jours' },
                { value: 'WEEKLY', label: 'semaines' },
                { value: 'MONTHLY', label: 'mois' },
                { value: 'YEARLY', label: 'années' },
              ]}
              onChange={(e) => handleChange({ freq: e.target.value as IcsRecurrenceRule['freq'] })}
            />
          </div>

          {value?.freq === 'WEEKLY' && (
            <div className="recurrence-editor-layout">
              <span>Répéter le</span>
              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--gap-0-5rem recurrence-editor-layout--margin-top-0-5rem">
                {WEEKDAYS.map(day => {
                  const isSelected = value?.byDay?.includes(day.value) || false;
                  return (
                    <button
                      key={day.value}
                      className={`recurrence-editor__weekday-button ${isSelected ? 'recurrence-editor__weekday-button--selected' : ''}`}
                      onClick={(e) => {
                        e.preventDefault();
                        const byDay = value?.byDay || [];
                        handleChange({
                          byDay: byDay.includes(day.value)
                            ? byDay.filter(d => d !== day.value)
                            : [...byDay, day.value]
                        });
                      }}
                    >
                      {day.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <div className="recurrence-editor-layout">
            <span>Se termine</span>
            <div className="recurrence-editor-layout recurrence-editor-layout--gap-0-5rem recurrence-editor-layout--margin-top-0-5rem">
              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-0-5rem">
                <input
                  type="radio"
                  name="end-type"
                  checked={!value?.count && !value?.until}
                  onChange={() => handleChange({ count: undefined, until: undefined })}
                />
                <span>Jamais</span>
              </div>

              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-0-5rem">
                <input
                  type="radio"
                  name="end-type"
                  checked={!!value?.until}
                  onChange={() => handleChange({ until: new Date(), count: undefined })}
                />
                <span>Le</span>
                {value?.until && (
                  <Input
                    type="date"
                    value={value.until.date ? new Date(value.until.date).toISOString().split('T')[0] : ''}
                    onChange={(e) => handleChange({ 
                      until: {
                        type: 'DATE-TIME',
                        date: new Date(e.target.value),
                        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                      }
                    })}
                  />
                )}
              </div>

              <div className="recurrence-editor-layout recurrence-editor-layout--row recurrence-editor-layout--align-center recurrence-editor-layout--gap-0-5rem">
                <input
                  type="radio"
                  name="end-type"
                  checked={!!value?.count}
                  onChange={() => handleChange({ count: 1, until: undefined })}
                />
                <span>Après</span>
                {value?.count !== undefined && (
                  <>
                    <Input
                      type="number"
                      min={1}
                      value={value.count}
                      onChange={(e) => handleChange({ count: parseInt(e.target.value) })}
                      style={{ width: '80px' }}
                    />
                    <span>occurrences</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
} 