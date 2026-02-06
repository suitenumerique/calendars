import { useState, useCallback, type KeyboardEvent } from "react";
import { Input } from "@gouvfr-lasuite/cunningham-react";
import { Badge } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";
import type { IcsAttendee, IcsOrganizer } from "ts-ics";

interface AttendeesInputProps {
  attendees: IcsAttendee[];
  onChange: (attendees: IcsAttendee[]) => void;
  organizerEmail?: string;
  organizer?: IcsOrganizer;
}

const isValidEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
};

type BadgeType =
  | "accent"
  | "neutral"
  | "danger"
  | "success"
  | "warning"
  | "info";

const getBadgeType = (partstat?: string): BadgeType => {
  switch (partstat) {
    case "ACCEPTED":
      return "success";
    case "DECLINED":
      return "danger";
    case "TENTATIVE":
      return "warning";
    default:
      return "neutral";
  }
};

const getPartstatIcon = (partstat?: string): string => {
  switch (partstat) {
    case "ACCEPTED":
      return "check_circle";
    case "DECLINED":
      return "cancel";
    case "TENTATIVE":
      return "help";
    default:
      return "schedule";
  }
};

export function AttendeesInput({
  attendees,
  onChange,
  organizerEmail,
  organizer,
}: AttendeesInputProps) {
  const { t } = useTranslation();
  const [inputValue, setInputValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const addAttendee = useCallback(() => {
    const email = inputValue.trim().toLowerCase();

    if (!email) {
      return;
    }

    if (!isValidEmail(email)) {
      setError(t("calendar.attendees.invalidEmail"));
      return;
    }

    if (attendees.some((a) => a.email.toLowerCase() === email)) {
      setError(t("calendar.attendees.alreadyAdded"));
      return;
    }

    if (organizerEmail && email === organizerEmail.toLowerCase()) {
      setError(t("calendar.attendees.cannotAddOrganizer"));
      return;
    }

    const newAttendee: IcsAttendee = {
      email,
      partstat: "NEEDS-ACTION",
      rsvp: true,
      role: "REQ-PARTICIPANT",
    };

    onChange([...attendees, newAttendee]);
    setInputValue("");
    setError(null);
  }, [inputValue, attendees, onChange, organizerEmail, t]);

  const removeAttendee = useCallback(
    (emailToRemove: string) => {
      onChange(attendees.filter((a) => a.email !== emailToRemove));
    },
    [attendees, onChange],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addAttendee();
      }
    },
    [addAttendee],
  );

  return (
    <div className="attendees-input">
      <div className="attendees-input__field">
        <Input
          label={t("calendar.attendees.label")}
          hideLabel
          placeholder={t("calendar.attendees.placeholder")}
          variant="classic"
          fullWidth
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={handleKeyDown}
          state={error ? "error" : "default"}
          text={error || undefined}
        />
      </div>

      <div className="attendees-input__pills">
        {organizer && attendees.length > 0 && (
          <Badge type={"success"} className="attendees-input__pill">
            <span className="material-icons">check_circle</span>
            {organizer.email}
            <span className="attendees-input__organizer-label">
              ({t("calendar.attendees.organizer")})
            </span>
          </Badge>
        )}
        {attendees.map((attendee) => (
          <Badge
            key={attendee.email}
            type={getBadgeType(attendee.partstat)}
            className="attendees-input__pill"
          >
            <span className="material-icons">
              {getPartstatIcon(attendee.partstat)}
            </span>
            {attendee.email}
            <button
              type="button"
              className="attendees-input__pill-remove"
              onClick={() => removeAttendee(attendee.email)}
              aria-label={t("calendar.attendees.remove")}
            >
              <span className="material-icons">close</span>
            </button>
          </Badge>
        ))}
      </div>
    </div>
  );
}
