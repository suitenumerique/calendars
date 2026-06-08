import { useAppContext } from "@/features/app/AppContext";
import { tokens } from "@/styles/cunningham-tokens";

type Theme = (typeof tokens.themes)["default"];

export const useCunninghamTheme = (): Theme => {
  const { theme } = useAppContext();
  const themes = tokens.themes as unknown as Record<string, Theme>;
  return themes[theme] ?? tokens.themes.default;
};

// Once the cunningham sass generated string is fixed, we can remove this function.
export const removeQuotes = (str: string) => {
  return str.replace(/^['"]|['"]$/g, "");
};
