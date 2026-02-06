import { useTranslation } from "react-i18next";
import type { IcsAttendee, IcsOrganizer } from "ts-ics";
import { AttendeesInput } from "../AttendeesInput";
import { SectionRow } from "./SectionRow";

interface AttendeesSectionProps {
  attendees: IcsAttendee[];
  onChange: (attendees: IcsAttendee[]) => void;
  organizerEmail?: string;
  organizer?: IcsOrganizer;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
}

export const AttendeesSection = ({
  attendees,
  onChange,
  organizerEmail,
  organizer,
  alwaysOpen,
  isExpanded,
  onToggle,
}: AttendeesSectionProps) => {
  const { t } = useTranslation();

  return (
    <SectionRow
      icon="group"
      label={t("calendar.event.sections.addAttendees")}
      isEmpty={attendees.length === 0}
      alwaysOpen={alwaysOpen}
      isExpanded={isExpanded}
      onToggle={onToggle}
      iconAlign="flex-start"
    >
      <AttendeesInput
        attendees={attendees}
        onChange={onChange}
        organizerEmail={organizerEmail}
        organizer={organizer}
      />
    </SectionRow>
  );
};
