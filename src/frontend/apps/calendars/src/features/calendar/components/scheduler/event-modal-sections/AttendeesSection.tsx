import { useTranslation } from "react-i18next";
import { AttendeesInput } from "../AttendeesInput";
import { SectionRow } from "./SectionRow";
import { GroupSvg } from "@/features/ui/icons/inline";

import type { IcsAttendee, IcsOrganizer } from "ts-ics";



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
      icon={<GroupSvg />}
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
