import { useTranslation } from "react-i18next";
import { Hero, Footer, HomeGutter, Icon, IconType } from "@gouvfr-lasuite/ui-kit";
import { login } from "@/features/auth/Auth";
import { useEffect } from "react";
import { addToast, ToasterItem } from "@/features/ui/components/toaster/Toaster";
import { Button } from "@gouvfr-lasuite/cunningham-react";
import { useConfig } from "@/features/config/ConfigProvider";
import { useThemeCustomization } from "@/hooks/useThemeCustomization";
import { DynamicCalendarLogo } from "@/features/ui/components/logo";

import banner from "@/assets/home/banner.svg";

export const HomePage = () => {
  const { t } = useTranslation();
  const { config } = useConfig();
  const footerCustomization = useThemeCustomization("footer");

  useEffect(() => {
    const failure = new URLSearchParams(window.location.search).get("auth_error");
    if (failure === "alpha") {
      addToast(
        <ToasterItem type="error">
          <Icon name="science" type={IconType.OUTLINED} aria-hidden />
          <span>{t("authentication.error.alpha")}</span>
        </ToasterItem>,
      );
    }
  }, [t]);

  return (
    <>
      <HomeGutter>
        <Hero
          logo={<DynamicCalendarLogo variant="icon" />}
          banner={banner}
          title={t("home.title")}
          subtitle={t("home.subtitle")}
          mainButton={
            <div className="c__hero__buttons">
              <div>
                <Button onClick={() => login()} fullWidth>
                  {t("home.main_button")}
                </Button>
              </div>

              <div>
                <Button
                  variant="bordered"
                  fullWidth
                  href={config?.FRONTEND_MORE_LINK}
                  target="_blank"
                >
                  {t("home.more")}
                </Button>
              </div>
            </div>
          }
        />
      </HomeGutter>
      <Footer {...footerCustomization} />
    </>
  );
};
