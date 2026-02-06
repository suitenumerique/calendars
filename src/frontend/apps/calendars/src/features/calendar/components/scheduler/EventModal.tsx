import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { IcsEvent, IcsOrganizer } from "ts-ics";
import {
  Button,
  Input,
  Modal,
  ModalSize,
  Select,
} from "@gouvfr-lasuite/cunningham-react";

import { useAuth } from "@/features/auth/Auth";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import { DeleteEventModal } from "./DeleteEventModal";
import { useEventForm } from "./hooks/useEventForm";
import { DateTimeSection } from "./event-modal-sections/DateTimeSection";
import { RecurrenceSection } from "./event-modal-sections/RecurrenceSection";
import { LocationSection } from "./event-modal-sections/LocationSection";
import { VideoConferenceSection } from "./event-modal-sections/VideoConferenceSection";
import { AttendeesSection } from "./event-modal-sections/AttendeesSection";
import { DescriptionSection } from "./event-modal-sections/DescriptionSection";
import { InvitationResponseSection } from "./event-modal-sections/InvitationResponseSection";
import { SectionPills } from "./event-modal-sections/SectionPills";
import type { EventModalProps, RecurringDeleteOption } from "./types";
import { SectionRow } from "./event-modal-sections/SectionRow";

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
  const [isLoading, setIsLoading] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  const organizer: IcsOrganizer | undefined =
    event?.organizer ||
    (user?.email
      ? { email: user.email, name: user.email.split("@")[0] }
      : undefined);

  const form = useEventForm({ event, calendarUrl, adapter, organizer, mode });

  // Check if current user is invited
  const currentUserAttendee = event?.attendees?.find(
    (att) =>
      user?.email && att.email.toLowerCase() === user.email.toLowerCase(),
  );
  const isInvited = !!(
    event?.organizer &&
    currentUserAttendee &&
    event.organizer.email !== user?.email
  );
  const currentParticipationStatus =
    currentUserAttendee?.partstat || "NEEDS-ACTION";

  const showError = (message: string) => {
    addToast(
      <ToasterItem type="error" closeButton>{message}</ToasterItem>,
    );
  };

  const handleSave = async () => {
    setIsLoading(true);
    try {
      const icsEvent = form.toIcsEvent();
      await onSave(icsEvent, form.selectedCalendarUrl);
      onClose();
    } catch (error) {
      console.error("Failed to save event:", error);
      showError(t("api.error.unexpected"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteConfirm = async (option?: RecurringDeleteOption) => {
    if (!onDelete || !event?.uid) return;
    setShowDeleteModal(false);
    setIsLoading(true);
    try {
      await onDelete(event as IcsEvent, form.selectedCalendarUrl, option);
      onClose();
    } catch (error) {
      console.error("Failed to delete event:", error);
      showError(t("api.error.unexpected"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleRespondToInvitation = async (
    status: "ACCEPTED" | "TENTATIVE" | "DECLINED",
  ) => {
    if (!onRespondToInvitation || !event) return;
    setIsLoading(true);
    try {
      await onRespondToInvitation(event as IcsEvent, status);
      form.setAttendees((prev) =>
        prev.map((att) =>
          user?.email && att.email.toLowerCase() === user.email.toLowerCase()
            ? { ...att, partstat: status }
            : att,
        ),
      );
    } catch (error) {
      console.error("Failed to respond to invitation:", error);
      showError(t("api.error.unexpected"));
    } finally {
      setIsLoading(false);
    }
  };

  const visioBaseUrl = process.env.NEXT_PUBLIC_VISIO_BASE_URL;

  const pills = useMemo(
    () => [
      ...(visioBaseUrl
        ? [
            {
              id: "videoConference" as const,
              icon: "videocam",
              label: t("calendar.event.sections.addVideoConference"),
            },
          ]
        : []),
      {
        id: "location" as const,
        icon: "place",
        label: t("calendar.event.location"),
      },
      {
        id: "description" as const,
        icon: "notes",
        label: t("calendar.event.description"),
      },
      {
        id: "recurrence" as const,
        icon: "repeat",
        label: t("calendar.recurrence.label"),
      },
      {
        id: "attendees" as const,
        icon: "group",
        label: t("calendar.event.attendees"),
      },
    ],
    [t, visioBaseUrl],
  );

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={ModalSize.MEDIUM}
        title={
          mode === "create"
            ? t("calendar.event.createTitle")
            : t("calendar.event.editTitle")
        }
        leftActions={
          mode === "edit" && onDelete ? (
            <Button
              color="error"
              onClick={() => setShowDeleteModal(true)}
              disabled={isLoading}
            >
              {t("calendar.event.delete")}
            </Button>
          ) : undefined
        }
        rightActions={
          <>
            <Button color="neutral" onClick={onClose} disabled={isLoading}>
              {t("calendar.event.cancel")}
            </Button>
            <Button
              color="brand"
              onClick={handleSave}
              disabled={isLoading || !form.title.trim()}
            >
              {isLoading ? "..." : t("calendar.event.save")}
            </Button>
          </>
        }
      >
        <div className="event-modal__content">
          <SectionRow
            icon="edit"
            label={t("calendar.event.calendar")}
            alwaysOpen={true}
          >
            <Input
              label={t("calendar.event.title")}
              hideLabel
              autoFocus={mode === "create"}
              value={form.title}
              onChange={(e) => form.setTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.preventDefault();
              }}
              fullWidth
              placeholder={t("calendar.event.titlePlaceholder")}
              variant="classic"
            />
          </SectionRow>
          <SectionRow
            icon="event"
            label={t("calendar.event.calendar")}
            alwaysOpen={true}
          >
            <Select
              label={t("calendar.event.calendar")}
              hideLabel
              value={form.selectedCalendarUrl}
              onChange={(e) =>
                form.setSelectedCalendarUrl(String(e.target.value))
              }
              options={calendars.map((cal) => ({
                value: cal.url,
                label: cal.displayName || cal.url,
              }))}
              variant="classic"
              fullWidth
            />
          </SectionRow>
          <DateTimeSection
            startDateTime={form.startDateTime}
            endDateTime={form.endDateTime}
            isAllDay={form.isAllDay}
            onStartChange={form.handleStartDateChange}
            onEndChange={form.setEndDateTime}
            onAllDayChange={form.handleAllDayChange}
          />
          {form.isSectionExpanded("recurrence") && (
            <RecurrenceSection
              recurrence={form.recurrence}
              onChange={form.setRecurrence}
              alwaysOpen
            />
          )}
          {isInvited && mode === "edit" && onRespondToInvitation && (
            <InvitationResponseSection
              organizer={event?.organizer}
              currentStatus={currentParticipationStatus}
              isLoading={isLoading}
              onRespond={handleRespondToInvitation}
            />
          )}
          {form.isSectionExpanded("videoConference") && (
            <VideoConferenceSection
              url={form.videoConferenceUrl}
              onChange={form.setVideoConferenceUrl}
              alwaysOpen
            />
          )}
          {form.isSectionExpanded("location") && (
            <LocationSection
              location={form.location}
              onChange={form.setLocation}
              alwaysOpen
            />
          )}

          {form.isSectionExpanded("attendees") && (
            <AttendeesSection
              attendees={form.attendees}
              onChange={form.setAttendees}
              organizerEmail={user?.email}
              organizer={organizer}
              alwaysOpen
            />
          )}
          {form.isSectionExpanded("description") && (
            <DescriptionSection
              description={form.description}
              onChange={form.setDescription}
              alwaysOpen
            />
          )}
          <SectionPills
            pills={pills}
            isSectionExpanded={form.isSectionExpanded}
            onToggle={form.toggleSection}
          />
        </div>
      </Modal>

      <DeleteEventModal
        isOpen={showDeleteModal}
        isRecurring={!!form.recurrence}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setShowDeleteModal(false)}
      />
    </>
  );
};
