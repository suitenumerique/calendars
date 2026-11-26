import { tokens } from "@/styles/cunningham-tokens";
import type { ColorVariant } from "./colorScheme";

const lightThemeOf = (baseTheme: string): string => {
  if (baseTheme === "dark") return "default";
  if (!baseTheme.endsWith("-dark")) return baseTheme;
  const name = baseTheme.replace(/-dark$/, "");
  return [name, `${name}-light`].find((theme) => theme in tokens.themes) ?? baseTheme;
};

/**
 * Return the Cunningham theme that shows a base theme in a variant.
 * Keep the base theme when it has no counterpart in that variant.
 */
export const themeForVariant = (baseTheme: string, variant: ColorVariant): string => {
  if (variant === "light") return lightThemeOf(baseTheme);
  if (baseTheme === "default") return "dark";
  const darkTheme = `${baseTheme.replace(/-light$/, "")}-dark`;
  return darkTheme in tokens.themes ? darkTheme : baseTheme;
};
