import { LaGaufreV2 } from "@gouvfr-lasuite/ui-kit";
import {
  removeQuotes,
  useCunninghamTheme,
} from "../../cunningham/useCunninghamTheme";
import { useConfig } from "@/features/config/ConfigProvider";
import { useAppContext } from "@/pages/_app";

export const Gaufre = () => {
  const { config } = useConfig();
  const { theme: themeName } = useAppContext();
  const isEnabled = config?.FRONTEND_LAGAUFRE_ENABLED ?? false;
  const theme = useCunninghamTheme();
  const widgetPath =
    config?.FRONTEND_LAGAUFRE_WIDGET_PATH ||
    removeQuotes(theme.components.gaufre.widgetPath);
  const apiUrl =
    config?.FRONTEND_LAGAUFRE_WIDGET_API_URL ||
    removeQuotes(theme.components.gaufre.apiUrl);

  if (!isEnabled) {
    return null;
  }

  return (
    <LaGaufreV2
      widgetPath={widgetPath}
      apiUrl={apiUrl}
      showMoreLimit={themeName === "anct" ? 100 : 6}
    />
  );
};
