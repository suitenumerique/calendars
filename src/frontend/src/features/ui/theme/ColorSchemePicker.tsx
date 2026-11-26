import { Button, DropdownMenu, Icon, IconType } from "@gouvfr-lasuite/ui-components";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppContext } from "@/features/app/AppContext";
import type { ColorScheme } from "./colorScheme";

const ICONS: Record<ColorScheme, string> = {
  system: "contrast",
  light: "light_mode",
  dark: "dark_mode",
};

const SCHEMES: ColorScheme[] = ["system", "light", "dark"];

export const ColorSchemePicker = () => {
  const { t } = useTranslation();
  const { colorScheme, setColorScheme } = useAppContext();
  const [isOpen, setIsOpen] = useState(false);

  const options = SCHEMES.map((scheme) => ({
    value: scheme,
    label: t(`settings.colorScheme.${scheme}`),
    icon: <Icon name={ICONS[scheme]} type={IconType.OUTLINED} />,
  }));

  return (
    <DropdownMenu
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      options={options}
      selectedValues={[colorScheme]}
      onSelectValue={(value) => setColorScheme(value as ColorScheme)}
    >
      <Button
        onClick={() => setIsOpen(!isOpen)}
        icon={<Icon name={ICONS[colorScheme]} type={IconType.OUTLINED} />}
        aria-label={`${t("settings.colorScheme.label")}: ${t(`settings.colorScheme.${colorScheme}`)}`}
        size="small"
        color="neutral"
        variant="tertiary"
      />
    </DropdownMenu>
  );
};
