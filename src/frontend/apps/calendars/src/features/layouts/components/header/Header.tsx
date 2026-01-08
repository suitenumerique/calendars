import { LanguagePicker, useResponsive } from "@gouvfr-lasuite/ui-kit";
import { useAuth } from "@/features/auth/Auth";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchAPI } from "@/features/api/fetchApi";
import { Feedback } from "@/features/feedback/Feedback";
import { Gaufre } from "@/features/ui/components/gaufre/Gaufre";
import { UserProfile } from "@/features/ui/components/user/UserProfile";

export const HeaderIcon = () => {
  return (
    <div className="calendars__header__left">
      <div className="calendars__header__logo" />
      <Feedback />
    </div>
  );
};

export const HeaderRight = () => {
  const { user } = useAuth();
  const { isTablet } = useResponsive();

  return (
    <>
      {!isTablet && (
        <>
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
