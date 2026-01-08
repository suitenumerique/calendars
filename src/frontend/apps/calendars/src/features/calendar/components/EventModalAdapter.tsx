/**
 * Adapter that bridges open-calendar's EventEditHandlers with React state.
 * The handlers update state, and the modal is rendered normally in React tree.
 */

import type { IcsEvent } from 'ts-ics';
import type { OpenCalendar } from '../hooks/useEventModal';

interface EventEditHandlers {
  onCreateEvent: (info: EventEditCreateInfo) => void;
  onSelectEvent: (info: EventEditSelectInfo) => void;
  onMoveResizeEvent: (info: EventEditMoveResizeInfo) => void;
  onDeleteEvent: (info: EventEditDeleteInfo) => void;
}

interface EventEditCreateInfo {
  jsEvent: Event;
  userContact?: any;
  event: IcsEvent;
  calendars: OpenCalendar[];
  vCards: any[];
  handleCreate: (event: { calendarUrl: string; event: IcsEvent }) => Promise<Response>;
}

interface EventEditSelectInfo {
  jsEvent: Event;
  userContact?: any;
  calendarUrl: string;
  event: IcsEvent;
  recurringEvent?: IcsEvent;
  calendars: OpenCalendar[];
  vCards: any[];
  handleUpdate: (event: { calendarUrl: string; event: IcsEvent }) => Promise<Response>;
  handleDelete: (event: { calendarUrl: string; event: IcsEvent }) => Promise<Response>;
}

interface EventEditMoveResizeInfo {
  jsEvent: Event;
  calendarUrl: string;
  userContact?: any;
  event: IcsEvent;
  recurringEvent?: IcsEvent;
  start: Date;
  end: Date;
  handleUpdate: (event: { calendarUrl: string; event: IcsEvent }) => Promise<Response>;
}

interface EventEditDeleteInfo {
  jsEvent: Event;
  calendarUrl: string;
  userContact?: any;
  event: IcsEvent;
  recurringEvent?: IcsEvent;
  handleDelete: (event: { calendarUrl: string; event: IcsEvent }) => Promise<Response>;
}

export interface ModalState {
  isOpen: boolean;
  mode: 'create' | 'edit';
  event: IcsEvent | null;
  calendarUrl: string;
  calendars: OpenCalendar[];
  handleSave: ((event: { calendarUrl: string; event: IcsEvent }) => Promise<Response>) | null;
  handleDelete: ((event: { calendarUrl: string; event: IcsEvent }) => Promise<Response>) | null;
}

/**
 * Creates EventEditHandlers that update the provided state setter.
 */
export function createEventModalHandlers(
  setState: (state: ModalState) => void,
  calendars: OpenCalendar[] | (() => OpenCalendar[])
): EventEditHandlers {
  const getCalendars = (): OpenCalendar[] => {
    return typeof calendars === 'function' ? calendars() : calendars;
  };
  
  return {
    onCreateEvent: ({ event, calendars: calList, handleCreate }: EventEditCreateInfo) => {
      setState({
        isOpen: true,
        mode: 'create',
        event,
        calendarUrl: calList[0]?.url || '',
        calendars: calList,
        handleSave: handleCreate,
        handleDelete: null,
      });
    },
    onSelectEvent: ({ calendarUrl, event, calendars: calList, handleUpdate, handleDelete }: EventEditSelectInfo) => {
      setState({
        isOpen: true,
        mode: 'edit',
        event,
        calendarUrl,
        calendars: calList,
        handleSave: handleUpdate,
        handleDelete,
      });
    },
    onMoveResizeEvent: ({ calendarUrl, event, start, end, handleUpdate }: EventEditMoveResizeInfo) => {
      const newEvent = { ...event };
      const startDelta = start.getTime() - event.start.date.getTime();
      newEvent.start = { ...newEvent.start, date: new Date(event.start.date.getTime() + startDelta) };
      if (event.end) {
        const endDelta = end.getTime() - event.end.date.getTime();
        newEvent.end = { ...newEvent.end, date: new Date(event.end.date.getTime() + endDelta) };
      }
      handleUpdate({ calendarUrl, event: newEvent });
    },
    onDeleteEvent: ({ calendarUrl, event, handleDelete }: EventEditDeleteInfo) => {
      handleDelete({ calendarUrl, event });
    },
  };
}
