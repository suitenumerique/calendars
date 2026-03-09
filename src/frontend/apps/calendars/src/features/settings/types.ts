export interface DaySchedule {
  start: string; // "HH:MM" format
  end: string; // "HH:MM" format
}

export type DayOfWeek =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";

export const DAYS_OF_WEEK: DayOfWeek[] = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
];

export type AvailabilityWhen =
  | { type: "recurring"; day: DayOfWeek }
  | { type: "specific"; date: string }; // "YYYY-MM-DD"

export interface AvailabilitySlot {
  id: string;
  when: AvailabilityWhen;
  start: string; // "HH:MM"
  end: string; // "HH:MM"
}

export type AvailabilitySlots = AvailabilitySlot[];

export const generateSlotId = (): string => crypto.randomUUID();

export const DEFAULT_AVAILABILITY: AvailabilitySlots = [
  { id: "d-mon", when: { type: "recurring", day: "monday" }, start: "09:00", end: "18:00" },
  { id: "d-tue", when: { type: "recurring", day: "tuesday" }, start: "09:00", end: "18:00" },
  { id: "d-wed", when: { type: "recurring", day: "wednesday" }, start: "09:00", end: "18:00" },
  { id: "d-thu", when: { type: "recurring", day: "thursday" }, start: "09:00", end: "18:00" },
  { id: "d-fri", when: { type: "recurring", day: "friday" }, start: "09:00", end: "18:00" },
];
