import { useTranslation } from "react-i18next";
import { AttendeesInput } from "../AttendeesInput";
import { SectionRow } from "./SectionRow";
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";

import type { IcsAttendee, IcsOrganizer } from "ts-ics";

interface AttendeesSectionProps {
  attendees: IcsAttendee[];
  onChange: (attendees: IcsAttendee[]) => void;
  organizerEmail?: string;
  organizer?: IcsOrganizer;
  alwaysOpen?: boolean;
  isExpanded?: boolean;
  onToggle?: () => void;
  onPendingInvalidChange?: (invalid: boolean) => void;
}

export const AttendeesSection = ({
  attendees,
  onChange,
  organizerEmail,
  organizer,
  alwaysOpen,
  isExpanded,
  onToggle,
  onPendingInvalidChange,
}: AttendeesSectionProps) => {
  const { t } = useTranslation();

  return (
    <SectionRow
      icon={<Icon name="group" type={IconType.OUTLINED} aria-hidden />}
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
        onPendingInvalidChange={onPendingInvalidChange}
      />
    </SectionRow>
  );
};
