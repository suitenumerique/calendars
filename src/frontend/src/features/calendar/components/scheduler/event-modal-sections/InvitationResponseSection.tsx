import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { SectionRow } from "./SectionRow";
import { Checkmark, QuestionMark, XMark } from "@gouvfr-lasuite/ui-kit/icons";
import { Icon, IconType } from "@gouvfr-lasuite/ui-kit";
import { getBadgeType, getPartstatIcon } from "../partstatBadge";

import type { IcsOrganizer } from "ts-ics";

type Partstat = "ACCEPTED" | "TENTATIVE" | "DECLINED" | "NEEDS-ACTION";

interface InvitationResponseSectionProps {
  organizer?: IcsOrganizer;
  currentStatus: Partstat | (string & {});
  isLoading: boolean;
  eventStatus?: string;
  onRespond: (status: "ACCEPTED" | "TENTATIVE" | "DECLINED") => void;
}

const statusLabelKey = (status: string) => {
  switch (status) {
    case "ACCEPTED":
      return "calendar.event.accepted";
    case "TENTATIVE":
      return "calendar.event.tentative";
    case "DECLINED":
      return "calendar.event.declined";
    default:
      return "calendar.event.needsAction";
  }
};

export const InvitationResponseSection = ({
  organizer,
  currentStatus,
  isLoading,
  eventStatus,
  onRespond,
}: InvitationResponseSectionProps) => {
  const { t } = useTranslation();
  const isCancelled = eventStatus === "CANCELLED";
  const organizerLabel = organizer?.name || organizer?.email;
  const badgeType = getBadgeType(currentStatus);
  const partstatIcon = getPartstatIcon(currentStatus);

  return (
    <SectionRow
      icon={<Icon name="event_available" type={IconType.OUTLINED} aria-hidden />}
      label={t("calendar.event.invitation")}
      alwaysOpen
      iconAlign="flex-start"
    >
      <div className="invitation-response">
        {organizerLabel && (
          <div className="invitation-response__organizer">
            {t("calendar.event.organizedBy")} <strong>{organizerLabel}</strong>
          </div>
        )}

        {isCancelled ? (
          <div className="invitation-response__cancelled">
            <Icon name="event_busy" type={IconType.OUTLINED} aria-hidden />
            {t("calendar.event.cancelledNotice")}
          </div>
        ) : (
          <>
            <div className="invitation-response__actions">
              <Button
                size="small"
                color={currentStatus === "ACCEPTED" ? "success" : "neutral"}
                onClick={() => onRespond("ACCEPTED")}
                disabled={isLoading || currentStatus === "ACCEPTED"}
                icon={<Checkmark />}
              >
                {t("calendar.event.accept")}
              </Button>
              <Button
                size="small"
                color={currentStatus === "TENTATIVE" ? "warning" : "neutral"}
                onClick={() => onRespond("TENTATIVE")}
                disabled={isLoading || currentStatus === "TENTATIVE"}
                icon={<QuestionMark />}
              >
                {t("calendar.event.maybe")}
              </Button>
              <Button
                size="small"
                color={currentStatus === "DECLINED" ? "error" : "neutral"}
                onClick={() => onRespond("DECLINED")}
                disabled={isLoading || currentStatus === "DECLINED"}
                icon={<XMark />}
              >
                {t("calendar.event.decline")}
              </Button>
            </div>

            <div
              className={`invitation-response__status invitation-response__status--${badgeType}`}
            >
              {partstatIcon}
              <span>
                {t("calendar.event.yourResponse")}:{" "}
                <strong>{t(statusLabelKey(currentStatus))}</strong>
              </span>
            </div>
          </>
        )}
      </div>
    </SectionRow>
  );
};
