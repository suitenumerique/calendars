/**
 * CalendarShareModal component.
 * Wraps the UI Kit ShareModal for managing calendar sharing via CalDAV.
 */

import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { ShareModal } from "@gouvfr-lasuite/ui-kit";

import { useCalendarContext } from "../../contexts";
import { useAuth } from "../../../auth/Auth";
import {
  addToast,
  ToasterItem,
} from "../../../ui/components/toaster/Toaster";
import type { CalDavCalendar } from "../../services/dav/types/caldav-service";

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

export const CalendarShareModal = ({
  isOpen,
  calendar,
  onClose,
}: CalendarShareModalProps) => {
  const { t } = useTranslation();
  const { caldavService, shareCalendar } = useCalendarContext();
  const { user } = useAuth();
  const [accesses, setAccesses] = useState<ShareAccess[]>([]);
  const [searchResults, setSearchResults] = useState<ShareUser[]>([]);
  const [loading, setLoading] = useState(false);

  const buildAccesses = useCallback(
    (sharees: ShareAccess[]) => {
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

  const fetchSharees = useCallback(async () => {
    if (!calendar) return;

    const result = await caldavService.getCalendarSharees(calendar.url);
    if (result.success && result.data) {
      const shareeAccesses = result.data.map((sharee) => {
        const email = sharee.href.replace(/^mailto:/, "");
        return {
          id: sharee.href,
          role: "read-write",
          user: {
            id: sharee.href,
            full_name: sharee.displayName || email,
            email,
          },
        };
      });
      setAccesses(buildAccesses(shareeAccesses));
    } else {
      setAccesses(buildAccesses([]));
    }
  }, [calendar, caldavService, buildAccesses]);

  useEffect(() => {
    if (isOpen && calendar) {
      fetchSharees();
    }
    if (!isOpen) {
      setAccesses([]);
      setSearchResults([]);
    }
  }, [isOpen, calendar, fetchSharees]);

  const handleSearchUsers = useCallback((query: string) => {
    if (EMAIL_REGEX.test(query.trim())) {
      const email = query.trim();
      setSearchResults([
        { id: email, email, full_name: email },
      ]);
    } else {
      setSearchResults([]);
    }
  }, []);

  const handleInviteUser = useCallback(
    async (users: ShareUser[]) => {
      if (!calendar || users.length === 0) return;

      setLoading(true);
      try {
        const user = users[0];
        const result = await shareCalendar(calendar.url, user.email);
        if (result.success) {
          addToast(
            <ToasterItem>
              {t("calendar.shareCalendar.success", {
                email: user.email,
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

  const invitationRoles = [
    { label: t("roles.editor"), value: "read-write" },
  ];

  const getAccessRoles = useCallback(
    (access: ShareAccess) => {
      if (access.role === "owner") {
        return [{ label: t("roles.owner"), value: "owner" }];
      }
      return [{ label: t("roles.editor"), value: "read-write" }];
    },
    [t],
  );

  return (
    <ShareModal
      isOpen={isOpen}
      onClose={onClose}
      modalTitle={t("calendar.shareCalendar.title")}
      accesses={accesses}
      getAccessRoles={getAccessRoles}
      onDeleteAccess={handleDeleteAccess}
      searchUsersResult={searchResults}
      onSearchUsers={handleSearchUsers}
      onInviteUser={handleInviteUser}
      searchPlaceholder={t("calendar.shareCalendar.emailPlaceholder")}
      invitationRoles={invitationRoles}
      hideInvitations
      loading={loading}
    />
  );
};
