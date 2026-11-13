import {
  useState,
  useCallback,
  useRef,
  useEffect,
  type ClipboardEvent,
  type KeyboardEvent,
} from "react";
import { Input, Badge } from "@gouvfr-lasuite/ui-components";
import { useTranslation } from "react-i18next";
import { useUserSearch, type UserSearchResult } from "@/features/users/hooks/useUserSearch";
import { filterSuggestions, isValidEmail, parseAttendeeList } from "./attendees-utils";
import { getBadgeType, getPartstatIcon } from "./partstatBadge";
import { CircleCheck, XMark } from "@gouvfr-lasuite/ui-components/icons";

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

  // A list of addresses is not a search query.
  const isList = parseAttendeeList(inputValue).attendees.length > 1;
  const { data: searchResults, isLoading: isSearching } = useUserSearch(isList ? "" : inputValue);

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

  const addAttendees = useCallback(
    (text: string, fullName?: string) => {
      const parsed = parseAttendeeList(text);

      if (parsed.attendees.length === 0) {
        if (parsed.invalid.length > 0) setError(t("calendar.attendees.invalidEmail"));
        return;
      }

      const present = new Set(attendees.map((a) => a.email.toLowerCase()));
      const organizerAddress = organizerEmail?.toLowerCase();
      const added = parsed.attendees
        .filter(({ email }) => !present.has(email) && email !== organizerAddress)
        .map(
          ({ email, cn = fullName }): IcsAttendee => ({
            email,
            partstat: "NEEDS-ACTION",
            rsvp: true,
            role: "REQ-PARTICIPANT",
            ...(cn && { cn }),
          }),
        );

      if (added.length > 0) onChange([...attendees, ...added]);

      const hasInvalid = parsed.invalid.length > 0;
      const onlyOrganizer =
        parsed.attendees.length === 1 && parsed.attendees[0].email === organizerAddress;
      if (!hasInvalid && onlyOrganizer) {
        setError(t("calendar.attendees.cannotAddOrganizer"));
        return;
      }

      setInputValue(parsed.invalid.join(", "));
      setError(hasInvalid ? t("calendar.attendees.invalidEmail") : null);
      setShowSuggestions(false);
      setHighlightedIndex(-1);
    },
    [attendees, onChange, organizerEmail, t],
  );

  // A single-line input drops line breaks, which joins the addresses of a pasted list.
  const handlePaste = useCallback((e: ClipboardEvent<HTMLInputElement>) => {
    const pasted = e.clipboardData.getData("text").trim();
    if (!/[\r\n]/.test(pasted)) return;

    e.preventDefault();
    const { value, selectionStart, selectionEnd } = e.currentTarget;
    const before = value.slice(0, selectionStart ?? value.length);
    const after = value.slice(selectionEnd ?? value.length);
    setInputValue(before + pasted.replace(/[\r\n]+/g, ", ") + after);
    setHighlightedIndex(-1);
    setError(null);
  }, []);

  const selectSuggestion = useCallback(
    (user: UserSearchResult) => {
      addAttendees(user.email, user.full_name);
    },
    [addAttendees],
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
          addAttendees(inputValue);
        }
      }
    },
    [shouldShowDropdown, suggestions, highlightedIndex, selectSuggestion, addAttendees, inputValue],
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
          onPaste={handlePaste}
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
