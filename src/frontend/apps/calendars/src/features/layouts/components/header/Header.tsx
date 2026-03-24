import {
  DropdownMenu,
  Icon,
  IconType,
  LanguagePicker,
  useResponsive,
} from "@gouvfr-lasuite/ui-kit";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useAuth } from "@/features/auth/Auth";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/router";
import { fetchAPI } from "@/features/api/fetchApi";
import { Feedback } from "@/features/feedback/Feedback";
import { Gaufre } from "@/features/ui/components/gaufre/Gaufre";
import { DynamicCalendarLogo } from "@/features/ui/components/logo";
import { UserProfile } from "@/features/ui/components/user/UserProfile";
import { FeatureFlag, useFeatureFlag } from "@/hooks/useFeatureFlag";

export const HeaderIcon = () => {
  const router = useRouter();

  return (
    <div className="calendars__header__left">
      <div
        onClick={() => void router.push("/")}
        style={{ cursor: "pointer" }}
        role="link"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter") void router.push("/");
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
  const router = useRouter();
  const { user } = useAuth();

  const isResourcesEnabled = useFeatureFlag(FeatureFlag.ADMIN_RESOURCES);
  const isChannelsEnabled = useFeatureFlag(FeatureFlag.ADMIN_CHANNELS);
  const isAvailabilitiesEnabled = useFeatureFlag(
    FeatureFlag.ADMIN_AVAILABILITIES,
  );

  if (!user) return null;

  const adminOptions = user.can_admin
    ? [
        ...(isResourcesEnabled
          ? [
              {
                label: t("resources.title"),
                icon: <Icon name="meeting_room" type={IconType.OUTLINED} />,
                callback: () => void router.push("/resources"),
              },
            ]
          : []),
        ...(isChannelsEnabled
          ? [
              {
                label: t("integrations.title"),
                icon: (
                  <Icon
                    name="integration_instructions"
                    type={IconType.OUTLINED}
                  />
                ),
                callback: () => void router.push("/integrations"),
              },
            ]
          : []),
      ]
    : [];

  const options = [
    ...(isAvailabilitiesEnabled
      ? [
          {
            label: t("settings.workingHours.title"),
            icon: <Icon name="schedule" type={IconType.OUTLINED} />,
            callback: () => void router.push("/settings"),
          },
        ]
      : []),
    ...adminOptions,
  ];

  if (options.length === 0) return null;

  return (
    <DropdownMenu
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      options={options}
    >
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
  const { user, refreshUser } = useAuth();
  const [selectedLanguage, setSelectedLanguage] = useState(user?.language);

  // We must set the language to lowercase because django does not use "en-US", but "en-us".

  const languages = [
    {
      label: "Français",
      value: "fr-fr",
      shortLabel: "FR",
      isChecked: selectedLanguage === "fr-fr",
    },
    {
      label: "English",
      value: "en-us",
      shortLabel: "EN",
      isChecked: selectedLanguage === "en-us",
    },
    {
      label: "Nederlands",
      value: "nl-nl",
      shortLabel: "NL",
      isChecked: selectedLanguage === "nl-nl",
    },
    {
      label: "Deutsch",
      value: "de-de",
      shortLabel: "DE",
      isChecked: selectedLanguage === "de-de",
    },
  ];

  const onChange = (value: string) => {
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

  return (
    <LanguagePicker
      languages={languages}
      size="small"
      onChange={onChange}
      compact
    />
  );
};
