import { tokens } from "@/styles/cunningham-tokens";
import type { ColorVariant } from "./colorScheme";

/**
 * Return the Cunningham theme that shows a base theme in a variant.
 * Keep the base theme when it has no dark counterpart.
 */
export const themeForVariant = (baseTheme: string, variant: ColorVariant): string => {
  if (variant === "light") return baseTheme;
  if (baseTheme === "default") return "dark";
  const darkTheme = `${baseTheme.replace(/-light$/, "")}-dark`;
  return darkTheme in tokens.themes ? darkTheme : baseTheme;
};
