export interface RecurrenceRule {
  frequency: 'DAILY' | 'WEEKLY' | 'MONTHLY' | 'YEARLY';
  interval?: number;
  until?: Date;
  count?: number;
  byDay?: string[];  // e.g., ['MO', 'WE', 'FR']
  byMonth?: number[];  // 1-12
  byMonthDay?: number[];  // 1-31
}

export interface Calendar {
  id: string;
  name: string;
  color: string;
  description?: string;
  is_default?: boolean;
  owner?: string;
}

export interface Event {
  id?: string;
  title: string;
  date: string;  // ISO date string (YYYY-MM-DD)
  endDate: string;  // ISO date string (YYYY-MM-DD)
  time?: string;  // Time string (HH:mm)
  endTime?: string;  // Time string (HH:mm)
  allDay: boolean;
  calendarId: string;
  location?: string;
  notes?: string;
  description?: string;
  recurrence?: RecurrenceRule;
  visibility?: 'default' | 'public' | 'private';
}
