import type { ReactNode } from "react";
import { CircleCheck, Clock, QuestionMark, XMark } from "@gouvfr-lasuite/ui-kit/icons";

export type PartstatBadgeType = "accent" | "neutral" | "danger" | "success" | "warning" | "info";

export const getBadgeType = (partstat?: string): PartstatBadgeType => {
  switch (partstat) {
    case "ACCEPTED":
      return "success";
    case "DECLINED":
      return "danger";
    case "TENTATIVE":
      return "warning";
    default:
      return "neutral";
  }
};

export const getPartstatIcon = (partstat?: string): ReactNode => {
  switch (partstat) {
    case "ACCEPTED":
      return <CircleCheck />;
    case "DECLINED":
      return <XMark />;
    case "TENTATIVE":
      return <QuestionMark />;
    default:
      return <Clock />;
  }
};
