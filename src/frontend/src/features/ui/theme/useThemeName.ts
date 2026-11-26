import { useAppContext } from "@/features/app/AppContext";
import { resolveVariant } from "./colorScheme";
import { themeForVariant } from "./themeForVariant";
import { usePrefersDark } from "./usePrefersDark";

export const useThemeName = () => {
  const { theme, colorScheme } = useAppContext();
  const prefersDark = usePrefersDark();
  return themeForVariant(theme, resolveVariant(colorScheme, prefersDark));
};
