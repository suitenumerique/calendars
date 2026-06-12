import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Modal, ModalSize } from "@gouvfr-lasuite/cunningham-react";
import { CalendarSelect } from "./CalendarSelect";
import { useAuth } from "@/features/auth/Auth";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import { DeleteEventModal } from "./DeleteEventModal";
import { RecurringEditModal } from "./RecurringEditModal";
import { useEventForm } from "./hooks/useEventForm";
import { DateTimeSection } from "./event-modal-sections/DateTimeSection";
import { RecurrenceSection } from "./event-modal-sections/RecurrenceSection";
import { LocationSection } from "./event-modal-sections/LocationSection";
import { VideoConferenceSection } from "./event-modal-sections/VideoConferenceSection";
import { AttendeesSection } from "./event-modal-sections/AttendeesSection";
import { ResourcesSection } from "./event-modal-sections/ResourcesSection";
import { DescriptionSection } from "./event-modal-sections/DescriptionSection";
import { VisibilitySection } from "./event-modal-sections/VisibilitySection";
import { InvitationResponseSection } from "./event-modal-sections/InvitationResponseSection";
import { FreeBusySection } from "./event-modal-sections/FreeBusySection";
import { SectionPills } from "./event-modal-sections/SectionPills";
import { useResourcePrincipals } from "@/features/resources/api/useResourcePrincipals";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useConfig } from "@/features/config/ConfigProvider";
import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";
import { SectionRow } from "./event-modal-sections/SectionRow";
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";
import { Meet, Pin, Calendar, Edit, Lock } from "@gouvfr-lasuite/ui-kit/icons";

import type { IcsEvent, IcsOrganizer } from "ts-ics";

import type { EventModalProps, RecurringDeleteOption, RecurringEditOption } from "./types";

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
  const isMobile = useIsMobile();
  const [isLoading, setIsLoading] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showEditRecurringModal, setShowEditRecurringModal] = useState(false);
  // True while the attendees field holds half-typed, invalid text — blocks Save
  // so we never silently drop a would-be attendee.
  const [attendeesPendingInvalid, setAttendeesPendingInvalid] = useState(false);
  const [pendingRsvpStatus, setPendingRsvpStatus] = useState<
    "ACCEPTED" | "TENTATIVE" | "DECLINED" | null
  >(null);

  const { resources: availableResources } = useResourcePrincipals();

  // Initial organizer from the prop-level calendarUrl — used only
  // for the form reset effect (useEventForm) so that switching the
  // dropdown doesn't wipe the form.
  const initialMailboxEmail = calendarUrl
    ? calendars.find((c) => c.url === calendarUrl)?.mailboxEmail
    : undefined;

  const initialOrganizer: IcsOrganizer | undefined =
    event?.organizer ||
    (initialMailboxEmail
      ? { email: initialMailboxEmail, name: initialMailboxEmail.split("@")[0] }
      : user?.email
        ? {
            email: user.email,
            name: user.full_name || user.email.split("@")[0],
          }
        : undefined);

  const form = useEventForm({
    event,
    calendarUrl,
    adapter,
    organizer: initialOrganizer,
    mode,
    availableResources,
  });

  // Organizer that tracks the *currently selected* calendar in the
  // dropdown — this is what gets written into the ICS on save and
  // shown in the attendees section.  When the user switches from a
  // personal calendar to a mailbox calendar the ORGANIZER must
  // become the mailbox email so SabreDAV sets X-LS-Is-Mailbox and
  // Django routes the invitation through the Messages API.
  const organizer: IcsOrganizer | undefined = useMemo(() => {
    if (event?.organizer) return event.organizer;
    const mbxEmail = form.selectedCalendarUrl
      ? calendars.find((c) => c.url === form.selectedCalendarUrl)?.mailboxEmail
      : undefined;
    if (mbxEmail) return { email: mbxEmail, name: mbxEmail.split("@")[0] };
    if (user?.email) {
      return {
        email: user.email,
        name: user.full_name || user.email.split("@")[0],
      };
    }
    return undefined;
  }, [event?.organizer, form.selectedCalendarUrl, calendars, user]);

  // Defensive fallback to keep a valid selection when the caller did
  // not pass one (e.g. "new event" from a context with no default
  // calendar). When `calendarUrl` is non-empty we trust it, even if
  // it isn't in `calendars` yet — the list may still be loading and
  // auto-snapping to calendars[0] here would stomp the correct choice.
  useEffect(() => {
    if (!isOpen || calendars.length === 0) return;
    if (calendarUrl) return;
    const currentIsValid = calendars.some((cal) => cal.url === form.selectedCalendarUrl);
    if (!currentIsValid) {
      form.setSelectedCalendarUrl(calendars[0].url);
    }
    // Depend on the specific form fields used inside this effect rather
    // than the whole ``form`` object — useEventForm returns a new object
    // reference on every render, so listing ``form`` here would re-run
    // (and re-evaluate the state-setting branch) on every render and
    // could amplify into a "Maximum update depth" loop together with
    // any sibling effect that also setState's on render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, calendars, calendarUrl, form.selectedCalendarUrl, form.setSelectedCalendarUrl]);

  // Check if current user is invited.
  // We deliberately exclude:
  //   - the organizer (RSVP'ing to your own invite is meaningless)
  //   - resources / rooms (CUTYPE=RESOURCE)
  //   - NON-PARTICIPANT roles (resources, informational attendees)
  // The CANCELLED case is still considered "invited" — the section
  // renders a cancelled notice instead of buttons.
  const currentUserAttendee = event?.attendees?.find(
    (att) => user?.email && att.email.toLowerCase() === user.email.toLowerCase(),
  );
  const isInvited = !!(
    event?.organizer &&
    currentUserAttendee &&
    event.organizer.email?.toLowerCase() !== user?.email?.toLowerCase() &&
    currentUserAttendee.cutype !== "RESOURCE" &&
    currentUserAttendee.role !== "NON-PARTICIPANT"
  );
  // Read the partstat from the form state, not from the event prop, so that
  // the section reflects in-flight RSVP changes in place (we update
  // form.attendees on success without re-pulling the event prop, and the
  // modal no longer auto-closes after responding).
  const currentParticipationStatus =
    form.attendees.find(
      (att) => user?.email && att.email.toLowerCase() === user.email.toLowerCase(),
    )?.partstat ||
    currentUserAttendee?.partstat ||
    "NEEDS-ACTION";

  const showError = (message: string) => {
    addToast(
      <ToasterItem type="error" closeButton>
        {message}
      </ToasterItem>,
    );
  };

  const isRecurringEvent = mode === "edit" && !!(event?.recurrenceRule || event?.recurrenceId);

  // `startDateTime` / `endDateTime` are local form strings
  // ("YYYY-MM-DDTHH:mm" or "YYYY-MM-DD" for all-day). They are sortable
  // lexicographically, which is enough to flag end-before-start without
  // pulling in timezone parsing here.
  const hasInvalidDateRange = useMemo(() => {
    if (!form.startDateTime || !form.endDateTime) return false;
    return form.endDateTime < form.startDateTime;
  }, [form.startDateTime, form.endDateTime]);

  const doSave = async (option?: RecurringEditOption) => {
    setIsLoading(true);
    try {
      const icsEvent = form.toIcsEvent();

      // Override organizer with the one matching the currently
      // selected calendar (may differ from the initial prop).
      if (organizer) {
        icsEvent.organizer = {
          email: organizer.email,
          name: organizer.name,
        };
      }

      await onSave(icsEvent, form.selectedCalendarUrl, option);
      onClose();
    } catch (error) {
      console.error("Failed to save event:", error);
      showError(t("api.error.unexpected"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    if (isRecurringEvent) {
      setShowEditRecurringModal(true);
      return;
    }
    await doSave();
  };

  const handleEditRecurringConfirm = async (option: RecurringEditOption) => {
    setShowEditRecurringModal(false);
    await doSave(option);
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

  const doRespondToInvitation = async (
    status: "ACCEPTED" | "TENTATIVE" | "DECLINED",
    option?: RecurringEditOption,
  ) => {
    if (!onRespondToInvitation || !event) return;
    setIsLoading(true);
    try {
      await onRespondToInvitation(event as IcsEvent, status, option);
      form.setAttendees((prev) =>
        prev.map((att) =>
          user?.email && att.email.toLowerCase() === user.email.toLowerCase()
            ? { ...att, partstat: status }
            : att,
        ),
      );
    } catch (error) {
      // Toast is shown by the parent handler; just stop the spinner.
      console.error("Failed to respond to invitation:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRespondToInvitation = async (status: "ACCEPTED" | "TENTATIVE" | "DECLINED") => {
    if (isRecurringEvent) {
      setPendingRsvpStatus(status);
      return;
    }
    await doRespondToInvitation(status);
  };

  const handleRsvpRecurringConfirm = async (option: RecurringEditOption) => {
    const status = pendingRsvpStatus;
    setPendingRsvpStatus(null);
    if (!status) return;
    await doRespondToInvitation(status, option);
  };

  const { config } = useConfig();
  const meetBaseUrl = config?.FRONTEND_MEET_BASE_URL;
  // Gate the "Find a time" (FreeBusySection) pill behind a feature
  // flag. The section issues VFREEBUSY queries against the CalDAV
  // scheduling outbox; deployments without that capability can hide
  // the pill entirely by setting FEATURE_EVENT_SCHEDULING=false.
  const isSchedulingEnabled = useFeatureFlag(FeatureFlag.EVENT_SCHEDULING);

  const pills = useMemo(
    () => [
      ...(meetBaseUrl
        ? [
            {
              id: "videoConference" as const,
              icon: <Meet />,
              label: t("calendar.event.sections.addVideoConference"),
            },
          ]
        : []),
      {
        id: "location" as const,
        icon: <Pin />,
        label: t("calendar.event.location"),
      },
      {
        id: "description" as const,
        icon: <Icon name="notes" type={IconType.OUTLINED} aria-hidden />,
        label: t("calendar.event.description"),
      },
      {
        id: "recurrence" as const,
        icon: <Icon name="repeat" type={IconType.OUTLINED} aria-hidden />,
        label: t("calendar.recurrence.label"),
      },
      {
        id: "attendees" as const,
        icon: <Icon name="group" type={IconType.OUTLINED} aria-hidden />,
        label: t("calendar.event.attendees"),
      },
      {
        id: "visibility" as const,
        icon: <Lock />,
        label: t("calendar.event.visibility.label"),
      },
      ...(availableResources.length > 0
        ? [
            {
              id: "resources" as const,
              icon: <Icon name="meeting_room" type={IconType.OUTLINED} aria-hidden />,
              label: t("calendar.event.sections.addResources"),
            },
          ]
        : []),
      ...(isSchedulingEnabled
        ? [
            {
              id: "scheduling" as const,
              icon: <Icon name="event_available" type={IconType.OUTLINED} aria-hidden />,
              label: t("scheduling.findATime"),
            },
          ]
        : []),
    ],
    [t, meetBaseUrl, availableResources.length, isSchedulingEnabled],
  );

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={isMobile ? ModalSize.FULL : ModalSize.MEDIUM}
        stickyFooter
        title={mode === "create" ? t("calendar.event.createTitle") : t("calendar.event.editTitle")}
        actions={
          // Single footer slot so the section pills and the action buttons
          // share one sticky footer: pills on top, buttons below. Only the
          // fields in the scroller above overflow.
          <div className="event-modal__footer">
            <SectionPills
              pills={pills}
              isSectionExpanded={form.isSectionExpanded}
              onToggle={form.toggleSection}
            />
            <div className="event-modal__footer-actions">
              {mode === "edit" && onDelete ? (
                <Button color="error" onClick={() => setShowDeleteModal(true)} disabled={isLoading}>
                  {t("calendar.event.delete")}
                </Button>
              ) : (
                <span />
              )}
              <div className="event-modal__footer-actions__right">
                <Button color="neutral" onClick={onClose} disabled={isLoading}>
                  {t("calendar.event.cancel")}
                </Button>
                <Button
                  color="brand"
                  onClick={handleSave}
                  disabled={
                    isLoading ||
                    !form.title.trim() ||
                    !form.selectedCalendarUrl ||
                    hasInvalidDateRange ||
                    attendeesPendingInvalid
                  }
                >
                  {isLoading ? "..." : t("calendar.event.save")}
                </Button>
              </div>
            </div>
          </div>
        }
      >
        <div className="event-modal__content">
          <SectionRow icon={<Edit />} label={t("calendar.event.calendar")} alwaysOpen={true}>
            <Input
              label={t("calendar.event.title")}
              hideLabel
              autoFocus={mode === "create"}
              value={form.title}
              onChange={(e) => form.setTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  // Submit on Enter, mirroring the Save button's guard so
                  // we never create an invalid event.
                  const canSave =
                    !isLoading &&
                    form.title.trim() &&
                    form.selectedCalendarUrl &&
                    !hasInvalidDateRange &&
                    !attendeesPendingInvalid;
                  if (canSave) handleSave();
                }
              }}
              fullWidth
              placeholder={t("calendar.event.titlePlaceholder")}
              variant="classic"
            />
          </SectionRow>
          <SectionRow icon={<Calendar />} label={t("calendar.event.calendar")} alwaysOpen={true}>
            <CalendarSelect
              calendars={calendars}
              value={form.selectedCalendarUrl}
              onChange={form.setSelectedCalendarUrl}
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
          {hasInvalidDateRange && (
            <p role="alert" className="event-modal__error">
              {t("calendar.event.endBeforeStart")}
            </p>
          )}
          {form.isSectionExpanded("recurrence") && (
            <RecurrenceSection
              recurrence={form.recurrence}
              onChange={form.setRecurrence}
              alwaysOpen
            />
          )}
          {form.isSectionExpanded("videoConference") && (
            <VideoConferenceSection
              url={form.videoConferenceUrl}
              onChange={form.setVideoConferenceUrl}
              baseUrl={meetBaseUrl || ""}
              alwaysOpen
            />
          )}
          {form.isSectionExpanded("location") && (
            <LocationSection location={form.location} onChange={form.setLocation} alwaysOpen />
          )}

          {form.isSectionExpanded("attendees") && (
            <>
              <AttendeesSection
                attendees={form.attendees}
                onChange={form.setAttendees}
                organizerEmail={organizer?.email ?? user?.email}
                organizer={organizer}
                onPendingInvalidChange={setAttendeesPendingInvalid}
                alwaysOpen
              />
              {form.attendees.length > 0 && (
                <p
                  style={{
                    fontSize: "0.75rem",
                    color: "#9ca3af",
                    margin: "-8px 0 8px 36px",
                    padding: 0,
                  }}
                >
                  {t("calendar.attendees.sentFrom", {
                    email:
                      calendars.find((c) => c.url === form.selectedCalendarUrl)?.mailboxEmail ||
                      config?.CALENDAR_INVITATION_FROM_EMAIL ||
                      "",
                  })}
                </p>
              )}
            </>
          )}
          {isSchedulingEnabled && form.isSectionExpanded("scheduling") && (
            <FreeBusySection
              attendees={form.attendees}
              resourceEmails={form.resources.map((r) => r.email).filter((e): e is string => !!e)}
              resourceNames={Object.fromEntries(
                form.resources.filter((r) => r.email).map((r) => [r.email!.toLowerCase(), r.name]),
              )}
              organizerEmail={user?.email}
              startDateTime={form.startDateTime}
              endDateTime={form.endDateTime}
              onStartChange={form.setStartDateTime}
              onEndChange={form.setEndDateTime}
              alwaysOpen
            />
          )}
          {availableResources.length > 0 && form.isSectionExpanded("resources") && (
            <ResourcesSection
              resources={form.resources}
              onChange={form.setResources}
              availableResources={availableResources}
              eventAttendees={form.attendees}
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
          {form.isSectionExpanded("visibility") && (
            <VisibilitySection
              visibility={form.visibility}
              onChange={form.setVisibility}
              alwaysOpen
            />
          )}
          {isInvited && mode === "edit" && onRespondToInvitation && (
            <InvitationResponseSection
              organizer={event?.organizer}
              currentStatus={currentParticipationStatus}
              isLoading={isLoading}
              eventStatus={event?.status}
              onRespond={handleRespondToInvitation}
            />
          )}
        </div>
      </Modal>

      <DeleteEventModal
        isOpen={showDeleteModal}
        isRecurring={isRecurringEvent}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setShowDeleteModal(false)}
      />

      <RecurringEditModal
        isOpen={showEditRecurringModal}
        onConfirm={handleEditRecurringConfirm}
        onCancel={() => setShowEditRecurringModal(false)}
      />

      <RecurringEditModal
        isOpen={pendingRsvpStatus !== null}
        onConfirm={handleRsvpRecurringConfirm}
        onCancel={() => setPendingRsvpStatus(null)}
        title={t("calendar.event.rsvpRecurringTitle")}
        prompt={t("calendar.event.rsvpRecurringPrompt")}
        confirmLabel={t("calendar.event.send")}
        disableFuture
      />
    </>
  );
};
