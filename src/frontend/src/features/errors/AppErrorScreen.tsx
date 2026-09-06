import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@gouvfr-lasuite/ui-components";

/**
 * Router-level error boundary fallback.
 *
 * Deliberately self-contained (inline layout, no app chrome) so it can
 * still render when the crash originates in layout or context code.
 */
export const AppErrorScreen = ({ error }: { error: unknown }) => {
  const { t } = useTranslation();

  useEffect(() => {
    console.error("Unhandled application error", error);
  }, [error]);

  return (
    <div
      role="alert"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "1rem",
        minHeight: "100vh",
        padding: "2rem",
        textAlign: "center",
      }}
    >
      <h1>{t("error_screen.title")}</h1>
      <p>{t("error_screen.description")}</p>
      <Button onClick={() => window.location.reload()}>{t("error_screen.reload")}</Button>
    </div>
  );
};
