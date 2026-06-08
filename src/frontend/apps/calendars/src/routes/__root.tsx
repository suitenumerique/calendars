import { createRootRoute, Outlet } from "@tanstack/react-router";
import { useEffect } from "react";
import {
  MutationCache,
  Query,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { CunninghamProvider } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";
import { AppContextProvider, useAppContext } from "@/features/app/AppContext";
import { AnalyticsProvider } from "@/features/analytics/AnalyticsProvider";
import { ConfigProvider } from "@/features/config/ConfigProvider";
import { LeftPanelProvider } from "@/features/layouts/contexts/LeftPanelContext";
import { APIError, errorToString } from "@/features/api/APIError";
import { capitalizeRegion } from "@/features/i18n/utils";
import { removeQuotes, useCunninghamTheme } from "@/features/ui/cunningham/useCunninghamTheme";
import { FeedbackFooterMobile } from "@/features/feedback/Feedback";
import { useDynamicFavicon } from "@/features/ui/hooks/useDynamicFavicon";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";

const onError = (error: Error, query: unknown) => {
  if ((query as Query).meta?.noGlobalError) {
    return;
  }
  // Don't show toast for 401/403 errors because the app handles them by
  // redirecting to the 401/403 page. So we don't want to show a toast before
  // the redirect, it would feels buggy.
  if (error instanceof APIError) {
    if (error.code === 401) {
      return;
    }
    if (error.code === 403 && !(query as Query).meta?.showErrorOn403) {
      return;
    }
  }
  addToast(
    <ToasterItem type="error">
      <span>{errorToString(error)}</span>
    </ToasterItem>,
  );
};

const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => onError(error, mutation),
  }),
  queryCache: new QueryCache({
    onError: (error, query) => onError(error, query),
  }),
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

const setFavicon = (href: string) => {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.type = "image/png";
  link.href = href;
};

const RootShell = () => {
  const { t, i18n } = useTranslation();
  const { theme } = useAppContext();
  const themeTokens = useCunninghamTheme();
  const dynamicFavicon = useDynamicFavicon();
  const faviconHref = dynamicFavicon || removeQuotes(themeTokens.components.favicon.src);

  useEffect(() => {
    document.title = t("app_title");
  }, [t]);

  useEffect(() => {
    if (faviconHref) setFavicon(faviconHref);
  }, [faviconHref]);

  return (
    <QueryClientProvider client={queryClient}>
      <CunninghamProvider currentLocale={capitalizeRegion(i18n.language)} theme={theme}>
        <ConfigProvider>
          <AnalyticsProvider>
            <LeftPanelProvider>
              <Outlet />
              <FeedbackFooterMobile />
            </LeftPanelProvider>
          </AnalyticsProvider>
        </ConfigProvider>
      </CunninghamProvider>
    </QueryClientProvider>
  );
};

const Root = () => (
  <AppContextProvider>
    <RootShell />
  </AppContextProvider>
);

export const Route = createRootRoute({
  component: Root,
});
