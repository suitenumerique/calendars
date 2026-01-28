"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface DynamicCalendarLogoProps {
  variant?: "header" | "icon";
  className?: string;
}

export const DynamicCalendarLogo = ({
  variant = "header",
  className,
}: DynamicCalendarLogoProps) => {
  const { t } = useTranslation();
  const [day, setDay] = useState<number | null>(null);

  useEffect(() => {
    setDay(new Date().getDate());
  }, []);

  const isIcon = variant === "icon";
  const isDoubleDigit = day !== null && day >= 10;

  return (
    <div
      className={`calendars__dynamic-logo ${isIcon ? "calendars__dynamic-logo--icon" : "calendars__dynamic-logo--header"} ${className ?? ""}`}
    >
      <img
        src={
          isIcon
            ? "/assets/cal_icon_no_number.svg"
            : "/assets/cal_logotype_text_no_number.svg"
        }
        alt={t("app_title")}
        className="calendars__dynamic-logo__img"
      />
      {day !== null && (
        <span
          className={`calendars__dynamic-logo__day ${isDoubleDigit ? "calendars__dynamic-logo__day--small" : ""}`}
        >
          {day}
        </span>
      )}
    </div>
  );
};
