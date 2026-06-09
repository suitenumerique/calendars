import { useState, useCallback, useRef, useEffect, type KeyboardEvent } from "react";
import { Input } from "@gouvfr-lasuite/cunningham-react";
import { Badge } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";
import { useUserSearch, type UserSearchResult } from "@/features/users/hooks/useUserSearch";
import { filterSuggestions, isValidEmail } from "./attendees-utils";
import { getBadgeType, getPartstatIcon } from "./partstatBadge";
import { CircleCheck, XMark } from "@gouvfr-lasuite/ui-kit/icons";

import type { IcsAttendee, IcsOrganizer } from "ts-ics";

interface AttendeesInputProps {
  attendees: IcsAttendee[];
  onChange: (attendees: IcsAttendee[]) => void;
  organizerEmail?: string;
  organizer?: IcsOrganizer;
  /** Reports whether the input holds non-empty text that isn't a valid email. */
  onPendingInvalidChange?: (invalid: boolean) => void;
}

export function AttendeesInput({
  attendees,
  onChange,
  organizerEmail,
  organizer,
  onPendingInvalidChange,
}: AttendeesInputProps) {
  const { t } = useTranslation();
  const [inputValue, setInputValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const { data: searchResults, isLoading: isSearching } = useUserSearch(inputValue);

  // Filter out already-added attendees and the organizer
  const suggestions = filterSuggestions(searchResults ?? [], attendees, organizerEmail);

  // Show suggestions when we have results or are searching with enough chars
  const trimmedInput = inputValue.trim();
  const shouldShowDropdown = showSuggestions && trimmedInput.length >= 3 && !isSearching;
  const hasNoResults =
    shouldShowDropdown && suggestions.length === 0 && searchResults !== undefined;

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Surface unsubmitted-but-invalid input so the parent (event modal) can keep
  // Save disabled instead of silently dropping a half-typed attendee on save.
  useEffect(() => {
    onPendingInvalidChange?.(trimmedInput !== "" && !isValidEmail(trimmedInput));
    return () => onPendingInvalidChange?.(false);
  }, [trimmedInput, onPendingInvalidChange]);

  const addAttendeeByEmail = useCallback(
    (email: string, fullName?: string) => {
      const normalized = email.trim().toLowerCase();
      if (!normalized) return;

      if (!isValidEmail(normalized)) {
        setError(t("calendar.attendees.invalidEmail"));
        return;
      }

      if (attendees.some((a) => a.email.toLowerCase() === normalized)) {
        setError(t("calendar.attendees.alreadyAdded"));
        return;
      }

      if (organizerEmail && normalized === organizerEmail.toLowerCase()) {
        setError(t("calendar.attendees.cannotAddOrganizer"));
        return;
      }

      const newAttendee: IcsAttendee = {
        email: normalized,
        partstat: "NEEDS-ACTION",
        rsvp: true,
        role: "REQ-PARTICIPANT",
        ...(fullName && { cn: fullName }),
      };

      onChange([...attendees, newAttendee]);
      setInputValue("");
      setError(null);
      setShowSuggestions(false);
      setHighlightedIndex(-1);
    },
    [attendees, onChange, organizerEmail, t],
  );

  const selectSuggestion = useCallback(
    (user: UserSearchResult) => {
      addAttendeeByEmail(user.email, user.full_name);
    },
    [addAttendeeByEmail],
  );

  const removeAttendee = useCallback(
    (emailToRemove: string) => {
      onChange(attendees.filter((a) => a.email !== emailToRemove));
    },
    [attendees, onChange],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        setShowSuggestions(false);
        setHighlightedIndex(-1);
        return;
      }

      if (
        shouldShowDropdown &&
        suggestions.length > 0 &&
        (e.key === "ArrowDown" || e.key === "ArrowUp")
      ) {
        e.preventDefault();
        setHighlightedIndex((prev) => {
          if (e.key === "ArrowDown") {
            return prev < suggestions.length - 1 ? prev + 1 : 0;
          }
          return prev > 0 ? prev - 1 : suggestions.length - 1;
        });
        return;
      }

      if (e.key === "Enter") {
        e.preventDefault();
        if (shouldShowDropdown && highlightedIndex >= 0 && highlightedIndex < suggestions.length) {
          selectSuggestion(suggestions[highlightedIndex]);
        } else {
          addAttendeeByEmail(inputValue);
        }
      }
    },
    [
      shouldShowDropdown,
      suggestions,
      highlightedIndex,
      selectSuggestion,
      addAttendeeByEmail,
      inputValue,
    ],
  );

  return (
    <div className="attendees-input" ref={containerRef}>
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
            setShowSuggestions(true);
            setHighlightedIndex(-1);
            if (error) setError(null);
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => setShowSuggestions(true)}
          state={error ? "error" : "default"}
          text={error || undefined}
        />

        {(shouldShowDropdown && suggestions.length > 0) || hasNoResults ? (
          <ul className="attendees-input__suggestions" role="listbox">
            {suggestions.map((user, index) => (
              <li
                key={user.id}
                role="option"
                aria-selected={index === highlightedIndex}
                className={`attendees-input__suggestion${
                  index === highlightedIndex ? " attendees-input__suggestion--highlighted" : ""
                }`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectSuggestion(user);
                }}
                onMouseEnter={() => setHighlightedIndex(index)}
              >
                <span className="attendees-input__suggestion-name">{user.full_name}</span>
                <span className="attendees-input__suggestion-email">{user.email}</span>
              </li>
            ))}
            {hasNoResults && (
              <li className="attendees-input__suggestion attendees-input__suggestion--empty">
                {t("calendar.attendees.noResults")}
              </li>
            )}
          </ul>
        ) : null}
      </div>

      <div className="attendees-input__pills">
        {organizer && attendees.length > 0 && (
          <Badge type={"success"} className="attendees-input__pill">
            <CircleCheck />
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
            {getPartstatIcon(attendee.partstat)}
            {attendee.email}
            <button
              type="button"
              className="attendees-input__pill-remove"
              onClick={() => removeAttendee(attendee.email)}
              aria-label={t("calendar.attendees.remove")}
            >
              <XMark />
            </button>
          </Badge>
        ))}
      </div>
    </div>
  );
}
