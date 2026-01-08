/**
 * CalendarView component using open-calendar (Algoo).
 * Renders a CalDAV-connected calendar view.
 */

import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/features/auth/Auth";
import { createEventModalHandlers, type ModalState } from "./EventModalAdapter";
import { useEventModal } from "../hooks/useEventModal";
import type { IcsEvent } from 'ts-ics';

interface CalendarViewProps {
  selectedDate?: Date;
  onSelectDate?: (date: Date) => void;
}

export const CalendarView = ({
  selectedDate = new Date(),
  onSelectDate,
}: CalendarViewProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const calendarRef = useRef<unknown>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalState, setModalState] = useState<ModalState>({
    isOpen: false,
    mode: 'create',
    event: null,
    calendarUrl: '',
    calendars: [],
    handleSave: null,
    handleDelete: null,
  });
  const { user } = useAuth();

  // Use the modal hook with state from adapter
  const modal = useEventModal({
    calendars: modalState.calendars,
    initialEvent: modalState.event,
    initialCalendarUrl: modalState.calendarUrl,
    onSubmit: async (event: IcsEvent, calendarUrl: string) => {
      if (modalState.handleSave) {
        await modalState.handleSave({ calendarUrl, event });
        setModalState(prev => ({ ...prev, isOpen: false }));
      }
    },
    onDelete: async (event: IcsEvent, calendarUrl: string) => {
      if (modalState.handleDelete) {
        await modalState.handleDelete({ calendarUrl, event });
        setModalState(prev => ({ ...prev, isOpen: false }));
      }
    },
  });

  // Sync modal state with adapter state
  useEffect(() => {
    if (modalState.isOpen) {
      // Always call open to update all state (event, mode, calendarUrl, calendars)
      modal.open(modalState.event, modalState.mode, modalState.calendarUrl, modalState.calendars);
    } else if (modal.isOpen) {
      modal.close();
    }
  }, [modalState.isOpen, modalState.event, modalState.mode, modalState.calendarUrl, modalState.calendars]);

  useEffect(() => {
    const initCalendar = async () => {
      if (!containerRef.current || !user) return;

      try {
        setIsLoading(true);
        setError(null);

        // Dynamically import open-calendar to avoid SSR issues (uses browser-only globals)
        const { createCalendar } = await import("open-dav-calendar");

        // Clear previous calendar instance
        if (containerRef.current) {
          containerRef.current.innerHTML = "";
        }

        // CalDAV server URL - proxied through Django backend
        // The proxy handles authentication via session cookies
        // open-calendar will discover calendars from this URL
        const caldavServerUrl = `${process.env.NEXT_PUBLIC_API_ORIGIN}/api/v1.0/caldav/`;

        // Create calendar with CalDAV source
        // Use fetchOptions with credentials to include cookies
        const calendar = await createCalendar(
          [
            {
              serverUrl: caldavServerUrl,
              fetchOptions: {
                credentials: "include" as RequestCredentials,
                headers: {
                  "Content-Type": "application/xml",
                },
              },
            },
          ],
          [], // No address books for now
          containerRef.current,
          {
            view: "timeGridWeek",
            views: ["dayGridMonth", "timeGridWeek", "timeGridDay", "listWeek"],
            locale: "fr",
            date: selectedDate,
            editable: true,
            // Use custom EventEditHandlers that update React state
            ...createEventModalHandlers(setModalState, []),
            onEventCreated: (info) => {
              console.log("Event created:", info);
            },
            onEventUpdated: (info) => {
              console.log("Event updated:", info);
            },
            onEventDeleted: (info) => {
              console.log("Event deleted:", info);
            },
          },
          {
            // French translations
            calendar: {
              today: "Aujourd'hui",
              month: "Mois",
              week: "Semaine",
              day: "Jour",
              list: "Liste",
            },
            event: {
              edit: "Modifier",
              delete: "Supprimer",
              save: "Enregistrer",
              cancel: "Annuler",
              title: "Titre",
              description: "Description",
              location: "Lieu",
              startDate: "Date de début",
              endDate: "Date de fin",
              allDay: "Journée entière",
            },
          }
        );

        calendarRef.current = calendar;
        setIsLoading(false);
      } catch (err) {
        console.error("Failed to initialize calendar:", err);
        setError(
          err instanceof Error
            ? err.message
            : "Erreur lors du chargement du calendrier"
        );
        setIsLoading(false);
      }
    };

    initCalendar();

    return () => {
      // Cleanup
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
      }
      calendarRef.current = null;
    };
  }, [user]);

  // Update calendar date when selectedDate changes
  useEffect(() => {
    if (calendarRef.current && selectedDate) {
      // open-calendar may have a method to set date
      // This depends on the CalendarElement API
    }
  }, [selectedDate]);

  if (!user) {
    return (
      <div className="calendar-view calendar-view--loading">
        <p>Connexion requise pour afficher le calendrier</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="calendar-view calendar-view--error">
        <p>{error}</p>
        <button onClick={() => window.location.reload()}>Réessayer</button>
      </div>
    );
  }

  return (
    <div className="calendar-view">
      {isLoading && (
        <div className="calendar-view__loading">
          <p>Chargement du calendrier...</p>
        </div>
      )}
      <div
        ref={containerRef}
        className="calendar-view__container"
        style={{ opacity: isLoading ? 0 : 1 }}
      />
      {modal.Modal}
    </div>
  );
};
