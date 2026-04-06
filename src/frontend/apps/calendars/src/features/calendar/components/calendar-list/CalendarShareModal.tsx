/**
 * CalendarShareModal component.
 * Wraps the UI Kit ShareModal for managing calendar sharing via CalDAV.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { ShareModal } from "@gouvfr-lasuite/ui-kit";

import { useCalendarContext } from "../../contexts";
import { useAuth } from "../../../auth/Auth";
import { useMailboxContext } from "@/features/mailbox/MailboxContext";
import {
  addToast,
  ToasterItem,
} from "../../../ui/components/toaster/Toaster";
import type {
  CalDavCalendar,
  SharePrivilege,
} from "../../services/dav/types/caldav-service";
import { fetchAPI } from "@/features/api/fetchApi";

interface CalendarShareModalProps {
  isOpen: boolean;
  calendar: CalDavCalendar | null;
  onClose: () => void;
}

type ShareUser = {
  id: string;
  full_name: string;
  email: string;
};

type ShareAccess = {
  id: string;
  role: string;
  user: ShareUser;
  can_delete?: boolean;
};

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const SHARE_ROLES: SharePrivilege[] = [
  "freebusy",
  "read",
  "read-write",
  "admin",
];

const ROLE_KEYS: Record<string, string> = {
  freebusy: "roles.freebusy",
  read: "roles.reader",
  "read-write": "roles.editor",
  admin: "roles.administrator",
  owner: "roles.owner",
};

export const CalendarShareModal = ({
  isOpen,
  calendar,
  onClose,
}: CalendarShareModalProps) => {
  const { t } = useTranslation();
  const { caldavService, shareCalendar } = useCalendarContext();
  const { user } = useAuth();
  const { isMailboxCalendar, getMailboxEmail, availableMailboxes } = useMailboxContext();
  const [accesses, setAccesses] = useState<ShareAccess[]>([]);
  const [searchResults, setSearchResults] = useState<ShareUser[]>([]);
  const [loading, setLoading] = useState(false);

  const buildAccesses = useCallback(
    (sharees: ShareAccess[], skipOwner = false) => {
      if (skipOwner) return sharees;
      const ownerAccess: ShareAccess | null = user
        ? {
            id: "owner",
            role: "owner",
            can_delete: false,
            user: {
              id: user.id,
              full_name: user.email,
              email: user.email,
            },
          }
        : null;
      return ownerAccess ? [ownerAccess, ...sharees] : sharees;
    },
    [user],
  );

  // For mailbox calendars, find the mailbox data and user's role
  const isMailbox = calendar ? isMailboxCalendar(calendar.url, calendar) : false;
  const mailboxEmail = calendar ? getMailboxEmail(calendar.url, calendar) : undefined;
  const mailboxData = useMemo(() => {
    if (!mailboxEmail) return null;
    return availableMailboxes.find((mb) => mb.email === mailboxEmail) ?? null;
  }, [mailboxEmail, availableMailboxes]);

  const mailboxUsers = useMemo(() => {
    if (!mailboxData) return new Set<string>();
    return new Set(mailboxData.users.map((u) => u.email));
  }, [mailboxData]);

  const isMailboxAdmin = mailboxData?.role === "admin";


  const fetchSharees = useCallback(async () => {
    if (!calendar) return;

    const result = await caldavService.getCalendarSharees(calendar.url);
    if (result.success && result.data) {
      const shareeAccesses = result.data
        // For mailbox calendars, filter out the owner row (the mailbox principal)
        .filter((sharee) => !(isMailbox && sharee.privilege === "owner"))
        .map((sharee) => {
        const email = sharee.href.replace(/^mailto:/, "");
        const isSyncManaged = isMailbox && mailboxUsers.has(email);
        return {
          id: sharee.href,
          role: sharee.privilege,
          can_delete: !isSyncManaged,
          is_sync_managed: isSyncManaged,
          user: {
            id: sharee.href,
            full_name: sharee.displayName || email,
            email,
          },
        };
      });
      setAccesses(buildAccesses(shareeAccesses, isMailbox));
    } else {
      setAccesses(buildAccesses([], isMailbox));
    }
  }, [calendar, caldavService, buildAccesses, isMailbox, mailboxUsers]);

  useEffect(() => {
    if (isOpen && calendar) {
      fetchSharees();
    }
    if (!isOpen) {
      setAccesses([]);
      setSearchResults([]);
    }
  }, [isOpen, calendar, fetchSharees]);

  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const handleSearchUsers = useCallback(
    (query: string) => {
      clearTimeout(searchTimerRef.current);
      const trimmed = query.trim();

      if (trimmed.length < 3) {
        // For very short queries, fall back to email-only matching
        if (EMAIL_REGEX.test(trimmed)) {
          setSearchResults([
            { id: trimmed, email: trimmed, full_name: trimmed },
          ]);
        } else {
          setSearchResults([]);
        }
        return;
      }

      // Debounce the API call
      searchTimerRef.current = setTimeout(async () => {
        try {
          const response = await fetchAPI("users/", {
            params: { q: trimmed },
          });
          const data = await response.json();
          const results: ShareUser[] = (data.results ?? []).map(
            (u: { id: string; email: string; full_name: string }) => ({
              id: u.id,
              email: u.email,
              full_name: u.full_name || u.email,
            }),
          );
          // Always allow raw email entry too
          if (
            EMAIL_REGEX.test(trimmed) &&
            !results.some(
              (r) => r.email.toLowerCase() === trimmed.toLowerCase(),
            )
          ) {
            results.push({
              id: trimmed,
              email: trimmed,
              full_name: trimmed,
            });
          }
          setSearchResults(results);
        } catch {
          // Fallback to email-only on API error
          if (EMAIL_REGEX.test(trimmed)) {
            setSearchResults([
              { id: trimmed, email: trimmed, full_name: trimmed },
            ]);
          } else {
            setSearchResults([]);
          }
        }
      }, 300);
    },
    [],
  );

  const handleInviteUser = useCallback(
    async (users: ShareUser[], role: string) => {
      if (!calendar || users.length === 0) return;

      setLoading(true);
      try {
        const invitedUser = users[0];
        const privilege = (
          SHARE_ROLES.includes(role as SharePrivilege) ? role : "read-write"
        ) as SharePrivilege;
        const result = await shareCalendar(
          calendar.url,
          invitedUser.email,
          privilege,
        );
        if (result.success) {
          addToast(
            <ToasterItem>
              {t("calendar.shareCalendar.success", {
                email: invitedUser.email,
              })}
            </ToasterItem>,
          );
          await fetchSharees();
        } else {
          addToast(
            <ToasterItem type="error">
              {result.error || t("calendar.shareCalendar.error")}
            </ToasterItem>,
          );
        }
      } catch {
        addToast(
          <ToasterItem type="error">
            {t("calendar.shareCalendar.error")}
          </ToasterItem>,
        );
      } finally {
        setLoading(false);
        setSearchResults([]);
      }
    },
    [calendar, shareCalendar, fetchSharees, t],
  );

  const handleUpdateAccess = useCallback(
    async (access: ShareAccess, role: string) => {
      if (!calendar) return;

      setLoading(true);
      try {
        const privilege = (
          SHARE_ROLES.includes(role as SharePrivilege) ? role : "read-write"
        ) as SharePrivilege;
        const email = access.user.email;
        const result = await shareCalendar(calendar.url, email, privilege);
        if (result.success) {
          await fetchSharees();
        } else {
          addToast(
            <ToasterItem type="error">
              {result.error || t("calendar.shareCalendar.error")}
            </ToasterItem>,
          );
        }
      } catch {
        addToast(
          <ToasterItem type="error">
            {t("calendar.shareCalendar.error")}
          </ToasterItem>,
        );
      } finally {
        setLoading(false);
      }
    },
    [calendar, shareCalendar, fetchSharees, t],
  );

  const handleDeleteAccess = useCallback(
    async (access: ShareAccess) => {
      if (!calendar) return;

      setLoading(true);
      try {
        const shareeHref = access.id.startsWith("mailto:")
          ? access.id
          : `mailto:${access.user.email}`;
        const result = await caldavService.unshareCalendar(
          calendar.url,
          shareeHref,
        );
        if (result.success) {
          await fetchSharees();
        } else {
          addToast(
            <ToasterItem type="error">
              {result.error || t("calendar.shareCalendar.error")}
            </ToasterItem>,
          );
        }
      } catch {
        addToast(
          <ToasterItem type="error">
            {t("calendar.shareCalendar.error")}
          </ToasterItem>,
        );
      } finally {
        setLoading(false);
      }
    },
    [calendar, caldavService, fetchSharees, t],
  );

  const makeRoles = (values: string[]) =>
    values.map((v) => ({ label: t(ROLE_KEYS[v] || v), value: v }));

  const invitationRoles = isMailbox
    ? makeRoles(["freebusy", "read"])
    : makeRoles(["freebusy", "read", "read-write", "admin"]);

  const getAccessRoles = (access: ShareAccess) => {
    if (access.role === "owner") {
      return makeRoles(["owner"]);
    }
    if ((access as ShareAccess & { is_sync_managed?: boolean }).is_sync_managed) {
      return makeRoles([access.role]);
    }
    return makeRoles(["freebusy", "read", "read-write", "admin"]);
  };

  return (
    <ShareModal
      isOpen={isOpen}
      onClose={onClose}
      modalTitle={t("calendar.shareCalendar.title")}
      accesses={accesses}
      getAccessRoles={getAccessRoles}
      canUpdate={!isMailbox || isMailboxAdmin}
      accessRoleTopMessage={(access: ShareAccess) =>
        (access as ShareAccess & { is_sync_managed?: boolean }).is_sync_managed
          ? t("calendar.shareCalendar.syncManagedHint")
          : undefined
      }
      onDeleteAccess={isMailbox && !isMailboxAdmin ? undefined : handleDeleteAccess}
      onUpdateAccess={isMailbox ? undefined : handleUpdateAccess}
      searchUsersResult={isMailbox && !isMailboxAdmin ? [] : searchResults}
      onSearchUsers={isMailbox && !isMailboxAdmin ? () => {} : handleSearchUsers}
      onInviteUser={isMailbox && !isMailboxAdmin ? () => {} : handleInviteUser}
      searchPlaceholder={t("calendar.shareCalendar.emailPlaceholder")}
      invitationRoles={invitationRoles}
      hideInvitations={isMailbox && !isMailboxAdmin}
      loading={loading}
    >
      {isMailbox && (
        <div style={{
          margin: "0 16px 12px",
          padding: "12px 16px",
          backgroundColor: "#f0f4ff",
          border: "1px solid #c5d4f0",
          borderRadius: "6px",
          fontSize: "14px",
          color: "#334155",
          display: "flex",
          gap: "10px",
          alignItems: "flex-start",
        }}>
          <span className="material-icons" style={{ fontSize: "20px", color: "#3b82f6", flexShrink: 0, marginTop: "1px" }}>info</span>
          <span>
            {isMailboxAdmin
              ? t("calendar.shareCalendar.mailboxInfoAdmin", { email: mailboxData?.email })
              : t("calendar.shareCalendar.mailboxInfoReadonly", { email: mailboxData?.email })}
          </span>
        </div>
      )}
    </ShareModal>
  );
};
