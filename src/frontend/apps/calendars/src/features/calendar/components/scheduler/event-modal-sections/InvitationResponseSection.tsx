import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import type { IcsOrganizer } from "ts-ics";

interface InvitationResponseSectionProps {
  organizer?: IcsOrganizer;
  currentStatus: string;
  isLoading: boolean;
  onRespond: (status: "ACCEPTED" | "TENTATIVE" | "DECLINED") => void;
}

export const InvitationResponseSection = ({
  organizer,
  currentStatus,
  isLoading,
  onRespond,
}: InvitationResponseSectionProps) => {
  const { t } = useTranslation();

  return (
    <div className="invitation-response">
      <div className="invitation-response__header">
        <span className="invitation-response__label">
          {t("calendar.event.invitation", { defaultValue: "Invitation" })}
        </span>
        <span className="invitation-response__organizer">
          {t("calendar.event.organizedBy", {
            defaultValue: "Organisé par",
          })}{" "}
          {organizer?.name || organizer?.email}
        </span>
      </div>
      <div className="invitation-response__actions">
        <Button
          size="small"
          color={currentStatus === "ACCEPTED" ? "success" : "neutral"}
          onClick={() => onRespond("ACCEPTED")}
          disabled={isLoading || currentStatus === "ACCEPTED"}
        >
          ✓ {t("calendar.event.accept", { defaultValue: "Accepter" })}
        </Button>
        <Button
          size="small"
          color={currentStatus === "TENTATIVE" ? "warning" : "neutral"}
          onClick={() => onRespond("TENTATIVE")}
          disabled={isLoading || currentStatus === "TENTATIVE"}
        >
          ? {t("calendar.event.maybe", { defaultValue: "Peut-être" })}
        </Button>
        <Button
          size="small"
          color={currentStatus === "DECLINED" ? "error" : "neutral"}
          onClick={() => onRespond("DECLINED")}
          disabled={isLoading || currentStatus === "DECLINED"}
        >
          ✗ {t("calendar.event.decline", { defaultValue: "Refuser" })}
        </Button>
      </div>
      {currentStatus && (
        <div className="invitation-response__status">
          {t("calendar.event.yourResponse", {
            defaultValue: "Votre réponse",
          })}
          :{" "}
          <strong>
            {currentStatus === "ACCEPTED" &&
              t("calendar.event.accepted", { defaultValue: "Accepté" })}
            {currentStatus === "TENTATIVE" &&
              t("calendar.event.tentative", { defaultValue: "Peut-être" })}
            {currentStatus === "DECLINED" &&
              t("calendar.event.declined", { defaultValue: "Refusé" })}
            {currentStatus === "NEEDS-ACTION" &&
              t("calendar.event.needsAction", {
                defaultValue: "En attente",
              })}
          </strong>
        </div>
      )}
    </div>
  );
};
