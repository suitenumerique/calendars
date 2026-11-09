import {
  Button,
  DropdownMenu,
  Icon,
  IconType,
  LanguagePicker,
  useResponsive,
} from "@gouvfr-lasuite/ui-components";
import { useAuth } from "@/features/auth/Auth";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "@tanstack/react-router";
import { fetchAPI } from "@/features/api/fetchApi";
import { Feedback } from "@/features/feedback/Feedback";
import { Gaufre } from "@/features/ui/components/gaufre/Gaufre";
import { useConfig } from "@/features/config/ConfigProvider";
import { getPickerLanguages, getPickerOptions } from "@/features/i18n/utils";
import { DynamicCalendarLogo } from "@/features/ui/components/logo";
import { UserProfile } from "@/features/ui/components/user/UserProfile";
import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";

export const HeaderIcon = () => {
  const navigate = useNavigate();

  return (
    <div className="calendars__header__left">
      <div
        onClick={() => void navigate({ to: "/" })}
        style={{ cursor: "pointer" }}
        role="link"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter") void navigate({ to: "/" });
        }}
      >
        <DynamicCalendarLogo variant="header" />
      </div>
      <Feedback />
    </div>
  );
};

const ApplicationMenu = () => {
  const [isOpen, setIsOpen] = useState(false);
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user } = useAuth();

  const isResourcesEnabled = useFeatureFlag(FeatureFlag.ADMIN_RESOURCES);
  const isChannelsEnabled = useFeatureFlag(FeatureFlag.ADMIN_CHANNELS);
  const isAvailabilitiesEnabled = useFeatureFlag(FeatureFlag.ADMIN_AVAILABILITIES);

  if (!user) return null;

  const adminOptions = user.can_admin
    ? [
        ...(isResourcesEnabled
          ? [
              {
                label: t("resources.title"),
                icon: <Icon name="meeting_room" type={IconType.OUTLINED} />,
                callback: () => void navigate({ to: "/resources" }),
              },
            ]
          : []),
        ...(isChannelsEnabled
          ? [
              {
                label: t("integrations.title"),
                icon: <Icon name="integration_instructions" type={IconType.OUTLINED} />,
                callback: () => void navigate({ to: "/integrations" }),
              },
            ]
          : []),
      ]
    : [];

  const options = [
    {
      label: t("settings.calendars.title"),
      icon: <Icon name="calendar_month" type={IconType.OUTLINED} />,
      callback: () => void navigate({ to: "/settings/calendars" }),
    },
    ...(isAvailabilitiesEnabled
      ? [
          {
            label: t("settings.workingHours.title"),
            icon: <Icon name="schedule" type={IconType.OUTLINED} />,
            callback: () => void navigate({ to: "/availabilities" }),
          },
        ]
      : []),
    ...adminOptions,
  ];

  return (
    <DropdownMenu isOpen={isOpen} onOpenChange={setIsOpen} options={options}>
      <Button
        onClick={() => setIsOpen(true)}
        icon={<Icon name="settings" type={IconType.OUTLINED} />}
        aria-label={t("settings.label")}
        color="brand"
        variant="tertiary"
      />
    </DropdownMenu>
  );
};

export const HeaderRight = () => {
  const { isTablet } = useResponsive();

  return (
    <>
      {!isTablet && (
        <>
          <ApplicationMenu />
          <Gaufre />
          <UserProfile />
        </>
      )}
    </>
  );
};

export const LanguagePickerUserMenu = () => {
  const { i18n } = useTranslation();
  const { config } = useConfig();
  const { user, refreshUser } = useAuth();
  const pickerLanguages = getPickerLanguages(
    config.LANGUAGES ?? [],
    Object.keys(i18n.options.resources ?? {}),
  );
  const [selectedLanguage, setSelectedLanguage] = useState(user?.language);

  // Sync the user's backend language into the picker state and into i18next on
  // load and whenever the user object updates. The backend value is the source
  // of truth — it's also used server-side for email invitations.
  useEffect(() => {
    if (!user?.language) return;
    setSelectedLanguage(user.language);
    if (i18n.language !== user.language) {
      i18n.changeLanguage(user.language).catch((err) => {
        console.error("Error changing language", err);
      });
    }
  }, [user?.language, i18n]);

  // The UI kit picker reads its first language, so it cannot render without one.
  if (pickerLanguages.length === 0) return null;

  // Use the language of the translations that i18next resolves. It can be a
  // fallback language. If there is none, use the requested language.
  const languages = getPickerOptions(
    pickerLanguages,
    selectedLanguage,
    i18n.resolvedLanguage ?? i18n.language,
  );

  const onChange = (value: string) => {
    // Ignore a click on the option for a UI language that the config does not offer.
    if (!pickerLanguages.some((language) => language.value === value)) return;
    setSelectedLanguage(value);
    i18n.changeLanguage(value).catch((err) => {
      console.error("Error changing language", err);
    });
    if (user) {
      fetchAPI(`users/${user.id}/`, {
        method: "PATCH",
        body: JSON.stringify({ language: value }),
      }).then(() => {
        void refreshUser?.();
      });
    }
  };

  return <LanguagePicker languages={languages} size="small" onChange={onChange} compact />;
};
