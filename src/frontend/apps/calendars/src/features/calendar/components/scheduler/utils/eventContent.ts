/**
 * Custom event content renderer for the scheduler.
 *
 * Adapts event display based on duration:
 *  - 15–30 min  → single line: "Title, HH:MM"
 *  - 45–60 min  → two lines: title  /  time + location
 *  - 75 min+    → title (up to 2 lines)  /  time + location
 */

import type { CalDavExtendedProps } from '../../../services/dav/EventCalendarAdapter';
import type {
  EventCalendarEvent,
  EventCalendarContent,
} from '../../../services/dav/types/event-calendar';
import { cleanEventForDisplay } from './eventDisplayRules';

export interface EventContentInfo {
  event: EventCalendarEvent;
  timeText: string;
  view: unknown;
}

const esc = (s: string): string =>
  s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

const fmtTime = (d: Date): string =>
  `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

export const createEventContent = (
  info: EventContentInfo,
): EventCalendarContent => {
  const { event } = info;
  const title = typeof event.title === 'string' ? event.title : '';

  // All-day events: just show the title
  if (event.allDay) {
    return {
      html: `<div class="ec-custom ec-custom--allday"><span class="ec-custom__title">${esc(title)}</span></div>`,
    };
  }

  const start =
    event.start instanceof Date ? event.start : new Date(event.start);
  const end = event.end
    ? event.end instanceof Date
      ? event.end
      : new Date(event.end)
    : start;
  const durationMin = Math.round(
    (end.getTime() - start.getTime()) / 60_000,
  );

  const extProps = event.extendedProps as CalDavExtendedProps | undefined;
  const cleaned = cleanEventForDisplay({
    description: extProps?.description ?? '',
    location: extProps?.location ?? '',
    url: extProps?.url ?? '',
  });
  const location = cleaned.location;
  const time = fmtTime(start);

  // ≤ 30 min — single line: "Title, HH:MM"
  if (durationMin <= 30) {
    return {
      html:
        `<div class="ec-custom ec-custom--compact">` +
        `<span class="ec-custom__title">${esc(title)}</span>` +
        `<span class="ec-custom__sep">, </span>` +
        `<span class="ec-custom__time">${esc(time)}</span>` +
        `</div>`,
    };
  }

  const details = location ? `${time}, ${location}` : time;

  // 45–60 min — two single lines
  if (durationMin <= 60) {
    return {
      html:
        `<div class="ec-custom ec-custom--medium">` +
        `<div class="ec-custom__title">${esc(title)}</div>` +
        `<div class="ec-custom__details">${esc(details)}</div>` +
        `</div>`,
    };
  }

  // 75 min+ — title wraps up to 2 lines, then details
  return {
    html:
      `<div class="ec-custom ec-custom--large">` +
      `<div class="ec-custom__title">${esc(title)}</div>` +
      `<div class="ec-custom__details">${esc(details)}</div>` +
      `</div>`,
  };
};
