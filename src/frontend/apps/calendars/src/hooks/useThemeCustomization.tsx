import { useConfig } from "@/features/config/ConfigProvider";
import { ThemeCustomization, LocalizedRecord } from "@/features/api/types";
import { splitLocaleCode } from "@/features/i18n/utils";
import { useTranslation } from "react-i18next";

export const useThemeCustomization = (key: keyof ThemeCustomization) => {
  const { config } = useConfig();
  const { i18n } = useTranslation();
  const language = splitLocaleCode(i18n.language).language;
  const themeCustomization = config?.theme_customization?.[key] as LocalizedRecord | undefined;
  return {
    ...(themeCustomization?.default ?? {}),
    ...(themeCustomization?.[language] ?? {}),
  };
};
