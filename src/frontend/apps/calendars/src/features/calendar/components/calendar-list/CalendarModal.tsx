/**
 * CalendarModal component.
 * Handles creation and editing of calendars.
 * Supports mailbox selection when Messages integration is enabled.
 * Can be used in onboarding mode (isOnboarding=true) for first-time users.
 */

import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  Modal,
  ModalSize,
  Select,
  VariantType,
} from "@gouvfr-lasuite/cunningham-react";
import { errorToString } from "@/features/api/APIError";
import { useAuth } from "@/features/auth/Auth";
import { useConfig } from "@/features/config/ConfigProvider";
import { useMailboxContext } from "@/features/mailbox/MailboxContext";

import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";
import { DEFAULT_COLORS } from "./constants";
import { ColorPicker } from "./ColorPicker";
import type { CalendarModalProps } from "./types";

const NO_MAILBOX_VALUE = "__none__";

export const CalendarModal = ({
  isOpen,
  mode,
  calendar,
  onClose,
  onSave,
  isOnboarding = false,
}: CalendarModalProps) => {
  const { t } = useTranslation();
  const { config } = useConfig();
  const { user } = useAuth();
  const { availableMailboxes } = useMailboxContext();

  const [name, setName] = useState("");
  const [color, setColor] = useState(DEFAULT_COLORS[0]);
  const [includeInAvailability, setIncludeInAvailability] = useState(true);
  const [selectedMailbox, setSelectedMailbox] = useState(NO_MAILBOX_VALUE);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const messagesEnabled = !!config?.FEATURE_MESSAGES_INTEGRATION;
  const availabilitiesEnabled = useFeatureFlag(FeatureFlag.ADMIN_AVAILABILITIES);

  // The modal can only create mailbox-backed calendars from mailboxes where
  // the user has sender/admin role; other mailboxes must be filtered out from
  // every code path so the select value can never reference a hidden option.
  const sendCapableMailboxes = useMemo(
    () =>
      availableMailboxes.filter(
        (mb) => mb.role === "sender" || mb.role === "admin",
      ),
    [availableMailboxes],
  );

  const hasMailboxes = messagesEnabled && sendCapableMailboxes.length > 0;

  // Default mailbox pre-selection: prefer the mailbox whose email
  // matches the current user (their personal identity), otherwise
  // fall back to standalone. Used by both onboarding and the regular
  // create modal so the two flows behave the same way.
  const defaultMailbox = useMemo(() => {
    if (!user?.email) return null;
    const target = user.email.toLowerCase();
    return (
      sendCapableMailboxes.find((mb) => mb.email.toLowerCase() === target) ??
      null
    );
  }, [sendCapableMailboxes, user?.email]);

  // Build mailbox options for the select
  const mailboxOptions = useMemo(
    () => [
      {
        label: t("calendar.createCalendar.noMailbox"),
        value: NO_MAILBOX_VALUE,
      },
      ...sendCapableMailboxes.map((mb) => ({
        label: mb.name ? `${mb.name} (${mb.email})` : mb.email,
        value: mb.email,
      })),
    ],
    [sendCapableMailboxes, t],
  );

  // Reset form when modal opens or calendar changes
  useEffect(() => {
    if (isOpen) {
      if (mode === "edit" && calendar) {
        setName(calendar.displayName || "");
        setColor(calendar.color || DEFAULT_COLORS[0]);
        setIncludeInAvailability(calendar.includeInAvailability ?? true);
        setSelectedMailbox(NO_MAILBOX_VALUE);
      } else {
        setColor(DEFAULT_COLORS[0]);
        if (defaultMailbox) {
          setSelectedMailbox(defaultMailbox.email);
          setName(defaultMailbox.name || "");
        } else {
          setSelectedMailbox(NO_MAILBOX_VALUE);
          setName(t("calendar.createCalendar.defaultName"));
        }
      }
      setError(null);
    }
  }, [isOpen, mode, calendar, defaultMailbox, t]);

  const handleSave = async () => {
    if (!name?.trim()) {
      setError(t("calendar.createCalendar.nameRequired"));
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const mailboxEmail =
        selectedMailbox !== NO_MAILBOX_VALUE ? selectedMailbox : undefined;
      await onSave(name.trim(), color, mailboxEmail, includeInAvailability);
      if (!isOnboarding) {
        onClose();
      }
    } catch (err) {
      setError(errorToString(err));
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    if (isOnboarding) {
      // Cannot dismiss onboarding modal
      return;
    }
    setName("");
    setColor(DEFAULT_COLORS[0]);
    setSelectedMailbox(NO_MAILBOX_VALUE);
    setError(null);
    onClose();
  };

  const title = isOnboarding
    ? t("calendar.onboarding.title")
    : mode === "create"
      ? t("calendar.createCalendar.title")
      : t("calendar.editCalendar.title");

  const saveLabel =
    mode === "create"
      ? t("calendar.createCalendar.create")
      : t("calendar.editCalendar.save");

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size={ModalSize.MEDIUM}
      title={title}
      closeOnClickOutside={!isOnboarding}
      hideCloseButton={isOnboarding}
      rightActions={
        <>
          {!isOnboarding && (
            <Button color="neutral" onClick={handleClose} disabled={isLoading}>
              {t("calendar.event.cancel")}
            </Button>
          )}
          <Button
            color="brand"
            onClick={handleSave}
            disabled={isLoading || !name?.trim()}
          >
            {isLoading ? "..." : saveLabel}
          </Button>
        </>
      }
    >
      <div className="calendar-modal__content">
        {isOnboarding && (
          <p className="calendar-modal__onboarding-text">
            {hasMailboxes
              ? t("calendar.onboarding.description")
              : t("calendar.onboarding.noMailboxesMessage")}
          </p>
        )}

        {error && (
          <Alert
            className="app__alert--small"
            type={VariantType.ERROR}
            icon={<span className="material-icons">error</span>}
          >
            {error}
          </Alert>
        )}

        {hasMailboxes && mode === "create" && (
          <div className="calendar-modal__field">
            <Select
              label={t("calendar.createCalendar.mailbox")}
              options={mailboxOptions}
              value={selectedMailbox}
              onChange={(e) => {
                // Cunningham's Select emits undefined when the user
                // clicks "Clear selection" — treat that as NO_MAILBOX.
                const raw = e.target.value;
                const value =
                  typeof raw === "string" && raw ? raw : NO_MAILBOX_VALUE;
                setSelectedMailbox(value);
                if (value !== NO_MAILBOX_VALUE) {
                  const mb = sendCapableMailboxes.find(
                    (m) => m.email === value,
                  );
                  setName(mb?.name || value);
                } else {
                  setName(t("calendar.createCalendar.defaultName"));
                }
              }}
              fullWidth
            />
            {selectedMailbox === NO_MAILBOX_VALUE && (
              <p className="calendar-modal__mailbox-hint">
                {t("calendar.createCalendar.noMailboxHint")}
              </p>
            )}
            {selectedMailbox !== NO_MAILBOX_VALUE && (
              <p className="calendar-modal__mailbox-hint">
                {t("calendar.createCalendar.mailboxHint", {
                  email: selectedMailbox,
                })}
              </p>
            )}
          </div>
        )}

        {!hasMailboxes && mode === "create" && !isOnboarding && (
          <p className="calendar-modal__mailbox-hint">
            {t("calendar.createCalendar.noMailboxAvailable")}
          </p>
        )}

        {mode === "edit" && calendar?.mailboxEmail && (
          <Alert
            className="app__alert--small"
            type={VariantType.INFO}
            icon={<span className="material-icons">mail</span>}
          >
            {t("calendar.editCalendar.linkedMailbox", { email: calendar.mailboxEmail })}
          </Alert>
        )}

        <Input
          label={t("calendar.createCalendar.name")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          fullWidth
        />

        <ColorPicker value={color} onChange={setColor} />

        {mode === "edit" && availabilitiesEnabled && (
          <label style={{ display: "flex", alignItems: "center", gap: "8px", padding: "8px 0", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={includeInAvailability}
              onChange={(e) => setIncludeInAvailability(e.target.checked)}
              style={{ width: "16px", height: "16px" }}
            />
            <span style={{ fontSize: "14px" }}>
              {t("calendar.editCalendar.includeInAvailability")}
            </span>
          </label>
        )}
      </div>
    </Modal>
  );
};
