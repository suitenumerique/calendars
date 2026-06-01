export type PartstatBadgeType =
  | "accent"
  | "neutral"
  | "danger"
  | "success"
  | "warning"
  | "info";

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

export const getPartstatIcon = (partstat?: string): string => {
  switch (partstat) {
    case "ACCEPTED":
      return "check_circle";
    case "DECLINED":
      return "cancel";
    case "TENTATIVE":
      return "help";
    default:
      return "schedule";
  }
};
