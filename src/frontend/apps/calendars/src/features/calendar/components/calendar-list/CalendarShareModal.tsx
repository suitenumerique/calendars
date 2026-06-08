/**
 * CalendarShareModal component.
 * Wraps the UI Kit ShareModal for managing calendar sharing via CalDAV.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { ShareModal } from "@gouvfr-lasuite/ui-kit";
import { Alert, VariantType } from "@gouvfr-lasuite/cunningham-react";
import { useCalendarContext } from "../../contexts";
import { useAuth } from "../../../auth/Auth";
import { useMailboxContext } from "@/features/mailbox/MailboxContext";
import { addToast, ToasterItem } from "../../../ui/components/toaster/Toaster";
import { fetchAPI } from "@/features/api/fetchApi";
import { Info } from "@gouvfr-lasuite/ui-kit/icons";

import type {
  CalDavCalendar,
  CalDavSharee,
  SharePrivilege,
} from "../../services/dav/types/caldav-service";

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

const SHARE_ROLES: SharePrivilege[] = ["freebusy", "read", "read-write", "admin"];

const ROLE_KEYS: Record<string, string> = {
  freebusy: "roles.freebusy",
  read: "roles.reader",
  "read-write": "roles.editor",
  admin: "roles.administrator",
  owner: "roles.owner",
};

export const CalendarShareModal = ({ isOpen, calendar, onClose }: CalendarShareModalProps) => {
  const { t } = useTranslation();
  const { caldavService, shareCalendar } = useCalendarContext();
  const { user } = useAuth();
  const { availableMailboxes } = useMailboxContext();
  // ``rawSharees`` is the latest source of truth for the share list:
  // it starts as ``calendar.sharees`` (already parsed from the standard
  // PROPFIND CS:invite payload) and gets replaced after every
  // invite/update/delete by re-fetching the calendar.
  const [rawSharees, setRawSharees] = useState<CalDavSharee[]>([]);
  const [searchResults, setSearchResults] = useState<ShareUser[]>([]);
  const [loading, setLoading] = useState(false);

  // Mailbox detection comes straight from the calendar's DAV
  // properties — both ``ownerType`` and ``mailboxEmail`` are populated
  // by ``parseCalendarPropfindResponse``, so they are stable from the
  // first render and never depend on ``useMailboxSync`` hydration.
  const isMailbox = calendar?.ownerType === "MAILBOX";
  const mailboxEmail = calendar?.mailboxEmail;

  const mailboxData = useMemo(() => {
    if (!mailboxEmail) return null;
    return availableMailboxes.find((mb) => mb.email === mailboxEmail) ?? null;
  }, [mailboxEmail, availableMailboxes]);

  const mailboxUsers = useMemo(() => {
    if (!mailboxData) return new Set<string>();
    return new Set(mailboxData.users.map((u) => u.email));
  }, [mailboxData]);

  const isMailboxAdmin = mailboxData?.role === "admin";

  // Seed/reset the share list when the modal opens or the calendar
  // changes. The initial sharees come from ``calendar.sharees`` —
  // already parsed by ``CalDavService`` — so we don't need an extra
  // PROPFIND just to render.
  useEffect(() => {
    if (isOpen && calendar) {
      setRawSharees(calendar.sharees ?? []);
    }
    if (!isOpen) {
      setRawSharees([]);
      setSearchResults([]);
    }
  }, [isOpen, calendar]);

  // Re-fetch the calendar to refresh its sharees after a mutation.
  // ``CS:invite`` rides on the standard calendar fetch, so this is a
  // single round-trip that keeps the modal in sync.
  const refreshSharees = useCallback(async () => {
    if (!calendar) return;
    const result = await caldavService.fetchCalendar(calendar.url);
    if (result.success && result.data) {
      setRawSharees(result.data.sharees ?? []);
    }
  }, [calendar, caldavService]);

  // Project the raw sharee list into the ShareModal's expected shape,
  // injecting the owner row at the top for non-mailbox calendars and
  // marking sync-managed entries as non-deletable.
  const accesses: ShareAccess[] = useMemo(() => {
    const shareeAccesses = rawSharees
      .filter((sharee) => !(isMailbox && (sharee.privilege as string) === "owner"))
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
        } as ShareAccess;
      });
    if (isMailbox || !user) return shareeAccesses;
    const ownerAccess: ShareAccess = {
      id: "owner",
      role: "owner",
      can_delete: false,
      user: {
        id: user.id,
        full_name: user.email,
        email: user.email,
      },
    };
    return [ownerAccess, ...shareeAccesses];
  }, [rawSharees, isMailbox, mailboxUsers, user]);

  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const handleSearchUsers = useCallback((query: string) => {
    clearTimeout(searchTimerRef.current);
    const trimmed = query.trim();

    if (trimmed.length < 3) {
      // For very short queries, fall back to email-only matching
      if (EMAIL_REGEX.test(trimmed)) {
        setSearchResults([{ id: trimmed, email: trimmed, full_name: trimmed }]);
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
          !results.some((r) => r.email.toLowerCase() === trimmed.toLowerCase())
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
          setSearchResults([{ id: trimmed, email: trimmed, full_name: trimmed }]);
        } else {
          setSearchResults([]);
        }
      }
    }, 300);
  }, []);

  const handleInviteUser = useCallback(
    async (users: ShareUser[], role: string) => {
      if (!calendar || users.length === 0) return;

      setLoading(true);
      try {
        const invitedUser = users[0];
        const privilege = (
          SHARE_ROLES.includes(role as SharePrivilege) ? role : "read-write"
        ) as SharePrivilege;
        const result = await shareCalendar(calendar.url, invitedUser.email, privilege);
        if (result.success) {
          addToast(
            <ToasterItem>
              {t("calendar.shareCalendar.success", {
                email: invitedUser.email,
              })}
            </ToasterItem>,
          );
          await refreshSharees();
        } else {
          addToast(
            <ToasterItem type="error">
              {result.error || t("calendar.shareCalendar.error")}
            </ToasterItem>,
          );
        }
      } catch {
        addToast(<ToasterItem type="error">{t("calendar.shareCalendar.error")}</ToasterItem>);
      } finally {
        setLoading(false);
        setSearchResults([]);
      }
    },
    [calendar, shareCalendar, refreshSharees, t],
  );

  const handleUpdateAccess = useCallback(
    async (access: ShareAccess, role: string) => {
      if (!calendar) return;

      // Sync-managed shares are owned by Messages — clicking the
      // (single) role in the dropdown must be a no-op. Otherwise the
      // ShareModal still fires onChange and we'd POST a CS:share that
      // the MailboxPlugin rightfully rejects with 403 (mailbox
      // calendars cannot be granted write access via manual sharing).
      if ((access as ShareAccess & { is_sync_managed?: boolean }).is_sync_managed) {
        return;
      }
      // Clicking the same role on a non-sync-managed entry is also a
      // no-op — there's nothing to update and the round-trip is wasted.
      if (role === access.role) {
        return;
      }

      setLoading(true);
      try {
        const privilege = (
          SHARE_ROLES.includes(role as SharePrivilege) ? role : "read-write"
        ) as SharePrivilege;
        const email = access.user.email;
        const result = await shareCalendar(calendar.url, email, privilege);
        if (result.success) {
          await refreshSharees();
        } else {
          addToast(
            <ToasterItem type="error">
              {result.error || t("calendar.shareCalendar.error")}
            </ToasterItem>,
          );
        }
      } catch {
        addToast(<ToasterItem type="error">{t("calendar.shareCalendar.error")}</ToasterItem>);
      } finally {
        setLoading(false);
      }
    },
    [calendar, shareCalendar, refreshSharees, t],
  );

  const handleDeleteAccess = useCallback(
    async (access: ShareAccess) => {
      if (!calendar) return;

      // Same guard as handleUpdateAccess: sync-managed rows belong to
      // Messages and must never be touched from this modal, even if a
      // delete handler somehow makes it through the per-row UI gates.
      if ((access as ShareAccess & { is_sync_managed?: boolean }).is_sync_managed) {
        return;
      }

      setLoading(true);
      try {
        const shareeHref = access.id.startsWith("mailto:")
          ? access.id
          : `mailto:${access.user.email}`;
        const result = await caldavService.unshareCalendar(calendar.url, shareeHref);
        if (result.success) {
          await refreshSharees();
        } else {
          addToast(
            <ToasterItem type="error">
              {result.error || t("calendar.shareCalendar.error")}
            </ToasterItem>,
          );
        }
      } catch {
        addToast(<ToasterItem type="error">{t("calendar.shareCalendar.error")}</ToasterItem>);
      } finally {
        setLoading(false);
      }
    },
    [calendar, caldavService, refreshSharees, t],
  );

  const makeRoles = (values: string[]) =>
    values.map((v) => ({ label: t(ROLE_KEYS[v] || v), value: v }));

  // The first entry is shown as the default in the invite dropdown
  // (ui-kit ShareModal uses ``invitationRoles[0].value``). Reader is
  // the safest, most common share level, so it leads.
  const invitationRoles = isMailbox
    ? makeRoles(["read", "freebusy"])
    : makeRoles(["read", "freebusy", "read-write", "admin"]);

  const getAccessRoles = (access: ShareAccess) => {
    if (access.role === "owner") {
      return makeRoles(["owner"]);
    }
    if ((access as ShareAccess & { is_sync_managed?: boolean }).is_sync_managed) {
      return makeRoles([access.role]);
    }
    // Mailbox calendars cap manual sharing at read-only (``freebusy``
    // rides on top of ``CS:read``). ``read-write`` and ``admin`` must
    // come via the Messages sync — ``MailboxPlugin::restrictSharing``
    // rejects them with 403 — so we don't even offer them in the
    // dropdown. This mirrors the same limitation already applied to
    // ``invitationRoles`` above.
    if (isMailbox) {
      return makeRoles(["read", "freebusy"]);
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
      onUpdateAccess={isMailbox && !isMailboxAdmin ? undefined : handleUpdateAccess}
      searchUsersResult={isMailbox && !isMailboxAdmin ? [] : searchResults}
      onSearchUsers={isMailbox && !isMailboxAdmin ? () => {} : handleSearchUsers}
      onInviteUser={isMailbox && !isMailboxAdmin ? () => {} : handleInviteUser}
      searchPlaceholder={t("calendar.shareCalendar.emailPlaceholder")}
      invitationRoles={invitationRoles}
      hideInvitations={isMailbox && !isMailboxAdmin}
      loading={loading}
    >
      {isMailbox && (
        <div style={{ margin: "0 16px 12px" }}>
          <Alert className="app__alert--small" type={VariantType.INFO} icon={<Info />}>
            {isMailboxAdmin
              ? t("calendar.shareCalendar.mailboxInfoAdmin", {
                  email: mailboxData?.email,
                })
              : t("calendar.shareCalendar.mailboxInfoReadonly", {
                  email: mailboxData?.email,
                })}
          </Alert>
        </div>
      )}
    </ShareModal>
  );
};
